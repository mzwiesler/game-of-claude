"""Insights: finds optimisation potential and recurring work in the last days of Claude Code sessions.

    python3 insights.py                       # analyse the last 7 days, save the report, print the findings
    python3 insights.py --claude              # plus written recommendations from `claude -p` (no tools, no transcript)
    python3 insights.py --days 14 --json      # print the whole report as JSON
    python3 insights.py --install-schedule    # Windows Task Scheduler: Mon–Fri 07:30 with --claude (--at HH:MM)
    python3 insights.py --schedule-status | --uninstall-schedule

Rules (FINDINGS below) look for friction that a setting, hook or script removes for good:
env prefixes retyped in Bash commands, sandbox bypasses, worktree-guard refusals, failing hooks,
MCP reconnects, retries, missing tools, expired tokens, stale permission allow entries, drifted
.claude files in worktrees, piling worktrees, requests that recur across sessions (candidates for
a skill or slash command), long and duplicated sessions (cost). Stdlib only, reads the transcripts
like collect.py.

Reports go to $XDG_DATA_HOME/claude-telemetry/insights/<date>.json and latest.json (next to the
XP ledger); the dashboard shows latest.json in its Insights card.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import ledger
from collect import CLAUDE_DIR, PROJECTS_DIR, _ts

HERE = Path(__file__).resolve().parent
DIR = ledger.PATH.parent / "insights"
KEEP = 60  # dated reports kept
DAYS = 7  # default look-back window
TASK = "Claude Telemetry Insights"
CLAUDE_MODEL = "sonnet"
CLAUDE_TIMEOUT = 900

# Requests worth a slash command or skill once they recur: (label, pattern, suggestion)
REQUESTS = (
    ("Check / debug a Terraform run", r"\b(tf|terraform)\b.{0,40}\b(run|plan)\b|latest run",
     "a `/tf-run [env]` command: fetch the latest run, plan logs, summarise drift and what to do"),
    ("Create or update a PR", r"\bcreate (a )?pr\b|\bpr \d+|push .{0,20}\bpr\b|\bopen (a )?pr\b",
     "a PR skill or `/ship` command with the repo's branch, commit and PR conventions"),
    ("Merge / clean up branches and worktrees", r"\bmerge\b|clean ?up|delete .{0,15}(merged|branch)|worktrees? (entfernen|löschen)",
     "a `/cleanup-merged` command: prune merged branches and remove their worktrees"),
    ("Create or draft a Jira ticket / issue", r"(create|draft|erstelle|schreibe).{0,25}\b(issue|ticket)s?\b",
     "a ticket skill with template, language, project keys and linking rules"),
    ("Look something up in Jira / Confluence", r"\b(jira|confluence)\b",
     "memory entries with the spaces, boards and ticket keys you use most"),
    ("Implement with subagents + review", r"\bsubagents?\b",
     "a `/impl-pr` command that encodes worktree → implement subagent → review subagent → PR"),
    ("Compare against other repos", r"\b(check|compare|vergleich\w*) .{0,40}\b(repo|repos|implementation)\b",
     "the reference repos and their paths in CLAUDE.md or memory"),
)
RETRY = re.compile(r"^(try again|check again|retry|nochmal|noch ?mal|versuch\w* (es )?nochmal)\b", re.I)
OUTSIDE_SANDBOX = re.compile(r"(outside|außerhalb)\b.{0,12}sandbox", re.I)
ENV_ASSIGN = re.compile(r"(?:^|&&|;|\|\|)\s*(?:export\s+)?([A-Z][A-Z0-9_]{3,})=\S*\s+(?=[a-z])|\bexport\s+([A-Z][A-Z0-9_]{3,})=")
MISSING_TOOL = re.compile(r"(\b[\w.-]+) is not installed|command not found: ([\w.-]+)|([\w.-]+): command not found|No such file or directory: '([\w.-]+)'")
AUTH = re.compile(r"authentication failed|token may be expired|\b401\b|unauthori[sz]ed", re.I)
ASSIGN = re.compile(r"^(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*=")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return ""


def _cmd_key(cmd: str) -> str:
    """First word of a Bash command, skipping leading `cd X`, `set -a` and VAR=value parts."""
    w = []
    for part in re.split(r"\s*(?:&&|;|\n)\s*", cmd.strip()):
        w = re.sub(r"\$\([^)]*\)", "x", part).split()  # VAR=$(ls -d …) is one word
        while w and ASSIGN.match(w[0]):
            w = w[1:]
        if w and w[0] not in ("cd", "set", "source", "."):
            break
    if not w:
        return "?"
    if w[0] in ("for", "while", "if"):
        return "loop"
    if w[0] in ("git", "gh", "az", "terraform", "kubectl", "docker", "podman", "npm", "uv", "python3", "databricks") and len(w) > 1:
        return f"{w[0]} {w[1]}"
    return w[0]


def _repo_root(cwd: str) -> str:
    return cwd.split("/.claude/worktrees/")[0]


# ---------- reading ----------

def scan(root: Path, since: datetime) -> list[dict]:
    """One summary per transcript with records since `since`. Subagent files keep their own
    entry (subagent=True) so their commands and errors count, their prompts don't."""
    out = []
    cutoff = since.timestamp()
    for path in root.glob("**/*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                continue
            lines = path.read_bytes().splitlines()
        except OSError:
            continue
        s = {"id": path.stem, "subagent": "subagents" in path.parts, "cwd": None, "start": None, "end": None,
             "prompts": [], "commands": [], "turns": 0, "out": 0, "cacheRead": 0, "compactions": 0,
             "tools": Counter(), "bash": [], "unsandboxed": [], "errors": [], "_names": {}, "_seen": set()}
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = _ts(rec.get("timestamp"))
            if ts and ts < since:
                continue
            _record(s, rec, ts)
        s.pop("_seen")
        s.pop("_names")
        if s["start"]:
            out.append(s)
    return out


def _record(s: dict, rec: dict, ts: datetime | None) -> None:
    typ = rec.get("type")
    if rec.get("isCompactSummary") or (typ == "system" and rec.get("subtype") == "compact_boundary"):
        s["compactions"] += 1
    if typ not in ("user", "assistant"):
        return
    if ts:
        s["start"] = min(s["start"] or ts, ts)
        s["end"] = max(s["end"] or ts, ts)
    s["cwd"] = s["cwd"] or rec.get("cwd")
    msg = rec.get("message") or {}
    content = msg.get("content")
    if typ == "user":
        if not rec.get("isMeta") and not rec.get("isSidechain") and not rec.get("isCompactSummary"):
            text = content if isinstance(content, str) else " ".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            m = re.search(r"<command-name>/?([^<]+)</command-name>", text)
            if m:
                s["commands"].append(m.group(1).strip())
            elif text.strip() and not text.startswith("<") and "[Request interrupted" not in text \
                    and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content or []):
                s["prompts"].append(" ".join(text.split()))
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                s["errors"].append((s["_names"].get(b.get("tool_use_id"), "?"), _text(b.get("content"))[:600]))
        return
    for b in content or []:
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        name, inp = b.get("name", "?"), b.get("input") or {}
        s["_names"][b.get("id")] = name
        s["tools"][name] += 1
        if name == "Bash":
            cmd = inp.get("command", "")
            s["bash"].append(cmd)
            if inp.get("dangerouslyDisableSandbox"):
                s["unsandboxed"].append(cmd)
    mid = msg.get("id") or rec.get("uuid")
    usage = msg.get("usage")
    if usage and mid not in s["_seen"] and msg.get("model") != "<synthetic>":
        s["_seen"].add(mid)
        s["turns"] += 1
        s["out"] += usage.get("output_tokens") or 0
        s["cacheRead"] += usage.get("cache_read_input_tokens") or 0


def read_settings() -> dict:
    try:
        return json.loads((CLAUDE_DIR / "settings.json").read_text())
    except (OSError, ValueError):
        return {}


# ---------- analysis ----------

def finding(fid: str, kind: str, severity: str, title: str, evidence: str, fix: str) -> dict:
    return {"id": fid, "kind": kind, "severity": severity, "title": title, "evidence": evidence, "fix": fix}


def top(counter: Counter, n: int = 4) -> str:
    return ", ".join(f"{k} {v}×" for k, v in counter.most_common(n))


def analyze(sessions: list[dict], settings: dict, days: int, now: datetime) -> dict:
    main = [s for s in sessions if not s["subagent"]]
    short = lambda p: (p or "?").replace(str(Path.home()), "~", 1)
    proj = lambda s: Path(_repo_root(s["cwd"] or "?")).name
    bash = [c for s in sessions for c in s["bash"]]
    errors = [e for s in sessions for e in s["errors"]]
    tools = Counter()
    for s in sessions:
        tools.update(s["tools"])
    prompts = [(s, p) for s in main for p in s["prompts"]]
    F = []

    # env prefixes retyped in commands: belong in settings.json "env"
    have_env = set((settings.get("env") or {}))
    env = Counter(n for c in bash for m in ENV_ASSIGN.finditer(c) for n in m.groups() if n and n not in have_env)
    env = Counter({k: v for k, v in env.items() if v >= 8})
    if env:
        F.append(finding("env-prefix", "friction", "medium", "Environment variables set by hand in Bash commands",
                         f"{top(env, 6)} across {sum(env.values())} commands",
                         "Set them once in ~/.claude/settings.json → \"env\" (or the repo's .claude/settings.json)."))

    # sandbox bypasses
    unsb = [c for s in sessions for c in s["unsandboxed"]]
    asks = sum(1 for _, p in prompts if OUTSIDE_SANDBOX.search(p))
    if len(unsb) >= 15 or asks >= 2:
        F.append(finding("sandbox", "friction", "high" if len(unsb) >= 50 else "medium", "Commands keep running outside the sandbox",
                         f"{len(unsb)} unsandboxed commands ({top(Counter(map(_cmd_key, unsb)), 5)}); you asked {asks}× to run outside the sandbox",
                         "Allow what they needed with /sandbox: localhost ports for dev servers, write access for CLI config dirs "
                         "(e.g. ~/.azure, ~/.cache), extra domains; or exclude trusted read-only CLIs."))

    # error classes
    by = defaultdict(list)
    for name, t in errors:
        if "isolated in the worktree" in t:
            by["worktree"].append(t)
        elif "hook error" in t:
            by["hook"].append(t.split("\n\n", 1)[-1].strip().split("\n")[0][:140])
        elif "auto mode classifier" in t and "denied" in t:
            by["classifier"].append(re.search(r"Reason: \[([^\]]+)\]", t).group(1) if "Reason: [" in t else "?")
        elif "doesn't want to proceed" in t:
            by["rejected"].append(name)
        elif name.startswith("mcp__") and AUTH.search(t):
            by["auth"].append(name.split("__")[1])
        else:
            m = MISSING_TOOL.search(t)
            if m:
                by["missing"].append(next(g for g in m.groups() if g))
    if len(by["worktree"]) >= 5:
        where = Counter(proj(s) for s in sessions for _, t in s["errors"] if "isolated in the worktree" in t)
        F.append(finding("worktree-guard", "friction", "medium", "Worktree guard refuses commands",
                         f"{len(by['worktree'])} refusals ({top(where)}): commands with runtime-computed values or loops around CLIs",
                         "Add to the repo's CLAUDE.md: in worktree sessions run plain single commands, no loops or $(…) around git/CLI calls."))
    if len(by["hook"]) >= 2:
        F.append(finding("hook", "friction", "medium", "A hook keeps blocking tool calls",
                         f"{len(by['hook'])}×: {top(Counter(by['hook']), 2)}",
                         "Let the hook fix what it can itself (e.g. run `terraform init -backend=false` when not initialised) instead of failing."))
    if len(by["auth"]) >= 2:
        F.append(finding("auth", "friction", "low", "MCP calls failed on expired credentials",
                         top(Counter(by["auth"])), "Renew the token(s) and check their expiry; a SessionStart hook can warn early."))
    if len(by["missing"]) >= 2:
        F.append(finding("missing-tool", "friction", "low", "Commands failed on missing tools",
                         top(Counter(by["missing"])), "Install them once (e.g. `sudo apt install poppler-utils` for pdftoppm)."))
    if len(by["classifier"]) >= 3:
        F.append(finding("classifier", "friction", "low", "Auto mode denied actions",
                         top(Counter(by["classifier"])), "If these are legitimate and recurring, add explicit allow rules for them."))

    # /mcp reconnects and retries
    mcp = Counter(proj(s) for s in main for c in s["commands"] if c in ("mcp", "reload-plugins"))
    if sum(mcp.values()) >= 3:
        F.append(finding("mcp-reconnect", "friction", "medium", "MCP servers needed manual reconnects",
                         f"{sum(mcp.values())}× /mcp or /reload-plugins ({top(mcp)})",
                         "Check the server's launcher: in worktrees a relative script path runs the worktree's (possibly stale) copy; "
                         "point .mcp.json at the main checkout, e.g. via `git rev-parse --git-common-dir`."))
    retries = [p for _, p in prompts if RETRY.match(p)]
    if len(retries) >= 3:
        F.append(finding("retry", "friction", "low", "You had to say \"try again\"",
                         f"{len(retries)} retry prompts", "Look at what failed before each retry (often auth, MCP or sandbox) and fix that cause."))

    # worktrees: piling up, and .claude files drifted from the main checkout
    roots = {_repo_root(s["cwd"]) for s in sessions if s["cwd"]}
    for r in sorted(roots):
        wt = Path(r, ".claude", "worktrees")
        if not wt.is_dir():
            continue
        trees = [d for d in wt.iterdir() if d.is_dir()]
        watched = [Path(r, ".mcp.json")] + [f for d in ("mcp", "hooks") for f in Path(r, ".claude", d).glob("*") if f.is_file()]
        drift = Counter()
        for t in trees:
            for f in watched:
                try:
                    if f.exists() and f.read_bytes() != (t / f.relative_to(r)).read_bytes():
                        drift[str(f.relative_to(r))] += 1
                except OSError:
                    drift[str(f.relative_to(r))] += 1
        if drift:
            F.append(finding(f"drift:{Path(r).name}", "friction", "high", f"Stale Claude config in {Path(r).name} worktrees",
                             f"{max(drift.values())} of {len(trees)} worktrees differ from main in {', '.join(drift)}",
                             "Rebase or remove old worktrees; better, let .mcp.json/hooks always run the main checkout's script."))
        if len(trees) >= 10:
            F.append(finding(f"worktrees:{Path(r).name}", "automation", "medium", f"{len(trees)} worktrees piling up in {Path(r).name}",
                             short(str(wt)), "A `/cleanup-merged` command: delete merged branches and `git worktree remove` their worktrees."))

    # stale permission allow entries for MCP servers
    used = Counter(n.split("__")[1] for n in tools.elements() if n.startswith("mcp__"))
    allowed = {e.split("__")[1] for e in (settings.get("permissions") or {}).get("allow", []) if e.startswith("mcp__")}
    stale, missing = allowed - set(used), {k for k, v in used.items() if v >= 15 and k not in allowed}
    if stale and missing:
        F.append(finding("allowlist", "friction", "low", "Permission allow list names MCP servers you no longer use",
                         f"allowed but unused: {', '.join(sorted(stale))}; used without allow entry: "
                         + ", ".join(f"{k} ({used[k]} calls)" for k in sorted(missing)),
                         "Rename the entries in ~/.claude/settings.json or run /fewer-permission-prompts."))

    # recurring requests: slash command / skill candidates
    for label, pat, fix in REQUESTS:
        hits = [(s["id"], p) for s, p in prompts if len(p) < 1500 and re.search(pat, p, re.I)]
        n_sess = len({i for i, _ in hits})
        if len(hits) >= 4 and n_sess >= 3:
            F.append(finding(f"request:{label}", "automation", "medium" if len(hits) >= 8 else "low", f"Recurring: {label}",
                             f"{len(hits)} prompts in {n_sess} sessions, e.g. \"{min((p for _, p in hits), key=len)[:90]}\"", f"Consider {fix}."))
    openers = Counter()
    first_words = {}
    for s in main:
        for p in {" ".join(re.findall(r"\w+", p.lower())[:4]) for p in s["prompts"] if len(p.split()) >= 4}:
            openers[p] += 1
            first_words.setdefault(p, s["id"])
    for o, n in openers.most_common(3):
        if n >= 3:
            F.append(finding(f"phrase:{o}", "automation", "low", f"Same request phrasing in {n} sessions",
                             f"\"{o} …\"", "If it is the same task each time, save it as a slash command."))

    # cost: long sessions and duplicate starts
    heavy = sorted((s for s in main if s["cacheRead"] >= 50e6 or s["compactions"] >= 2), key=lambda s: -s["cacheRead"])
    total_cr = sum(s["cacheRead"] for s in sessions)
    if heavy:
        F.append(finding("long-sessions", "cost", "medium", "Long sessions dominate the token use",
                         f"{len(heavy)} sessions = {sum(s['cacheRead'] for s in heavy) / max(1, total_cr):.0%} of {total_cr / 1e6:.0f}M cache-read tokens: "
                         + ", ".join(f"{proj(s)} {s['cacheRead'] / 1e6:.0f}M" + (f" ({s['compactions']}× compacted)" if s["compactions"] else "")
                                     for s in heavy[:4]),
                         "Start a fresh session (/clear) when the topic changes; hand over state via a short note or memory instead of carrying the whole context."))
    starts = sorted((s for s in main if s["prompts"] and len(s["prompts"][0]) >= 20), key=lambda s: s["start"])
    dups = []
    for i, a in enumerate(starts):
        for b in starts[i + 1:]:
            if (b["start"] - a["start"]).total_seconds() > 900:
                break
            if a["prompts"][0][:120].lower() == b["prompts"][0][:120].lower() or \
                    (a["prompts"][0].split()[:6] == b["prompts"][0].split()[:6] and len(a["prompts"][0].split()) >= 6):
                dups.append(f"\"{a['prompts'][0][:60]}\" ({proj(a)} / {proj(b)})")
    if dups:
        F.append(finding("duplicates", "cost", "low", "Same task started twice in parallel",
                         "; ".join(dups[:3]), "Check the job list before starting; one of each pair was wasted work."))
    empty = [s for s in main if not s["turns"]]
    logins = sum(c == "login" for s in main for c in s["commands"])
    if len(empty) >= 4:
        F.append(finding("empty", "friction", "low", "Many sessions ended without a single answer",
                         f"{len(empty)} empty sessions, {logins}× /login",
                         "Usually login or startup trouble; if it recurs check `claude doctor` and the token expiry."))

    order = {"high": 0, "medium": 1, "low": 2}
    F.sort(key=lambda f: (order[f["severity"]], f["kind"] != "friction"))
    cmds = Counter(c for s in main for c in s["commands"])
    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "days": days,
        "since": (now - timedelta(days=days)).isoformat(timespec="seconds"),
        "stats": {
            "sessions": len(main), "subagents": len(sessions) - len(main), "prompts": len(prompts),
            "projects": len({proj(s) for s in main}), "toolCalls": sum(tools.values()), "bash": len(bash),
            "toolErrors": len(errors), "unsandboxed": len(unsb),
            "outputTokens": sum(s["out"] for s in sessions), "cacheReadTokens": total_cr,
        },
        "findings": F,
        "topBash": Counter(map(_cmd_key, bash)).most_common(15),
        "topTools": tools.most_common(15),
        "slashCommands": cmds.most_common(10),
        "projects": Counter(proj(s) for s in main).most_common(12),
        "review": None,
    }


# ---------- Claude review ----------

def claude_review(report: dict, sessions: list[dict], model: str) -> dict:
    """Written recommendations from `claude -p`: no tools, no MCP, no saved session (so the
    review never shows up in later reports or the game)."""
    exe = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    lines = []
    for s in sorted((s for s in sessions if not s["subagent"] and s["prompts"]), key=lambda s: s["start"]):
        lines.append(f"## {Path(_repo_root(s['cwd'] or '?')).name} · {s['start']:%a %H:%M}–{s['end']:%H:%M} · "
                     f"{s['out'] // 1000}k out · {s['cacheRead'] // 1_000_000}M cache read · tools {dict(s['tools'].most_common(5))}")
        lines += [f"> {p[:220]}" for p in s["prompts"][:12]]
    ctx = {k: report[k] for k in ("days", "stats", "findings", "topBash", "topTools", "slashCommands", "projects")}
    prompt = f"""You review how a developer used Claude Code over the last {report['days']} days, to find optimisation
potential and recurring work they could automate (slash commands, skills, hooks, settings, memory, scripts).

Below: computed metrics and rule-based findings (JSON), then each session's first prompts.
Write Markdown, at most ~350 words, in English, with exactly these sections:
### Top 3 actions
Numbered, highest impact first; each names the concrete change (file, command or skill name) and the evidence.
### Automation candidates
Bullets for recurring tasks not already covered by the findings; say what the command/skill would do.
### Habits
At most 3 bullets on session or cost habits.
Do not restate the metrics, do not invent numbers, skip a point when the evidence is thin.

```json
{json.dumps(ctx, default=str)}
```

{chr(10).join(lines)[:60000]}
"""
    cmd = [exe, "-p", "--model", model, "--tools", "", "--no-session-persistence", "--strict-mcp-config",
           "--output-format", "text"]
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT, cwd=Path.home())
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": repr(e)[:300], "model": model}
    if r.returncode or not r.stdout.strip():
        return {"ok": False, "error": (r.stderr or r.stdout or f"exit {r.returncode}").strip()[-300:], "model": model}
    return {"ok": True, "markdown": r.stdout.strip(), "model": model, "seconds": round(time.monotonic() - t0)}


# ---------- reports ----------

def save(report: dict, out_dir: Path = DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(report, indent=1, default=str)
    path = out_dir / f"{report['generatedAt'][:10]}.json"
    for p in (path, out_dir / "latest.json"):
        tmp = p.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(p)
    for old in sorted(out_dir.glob("20*.json"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


_latest: tuple[float, dict | None] = (0.0, None)


def latest(out_dir: Path = DIR) -> dict | None:
    """The newest report for the dashboard, re-read only when the file changed."""
    global _latest
    p = out_dir / "latest.json"
    try:
        mtime = p.stat().st_mtime
        if mtime != _latest[0]:
            _latest = (mtime, json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    return _latest[1]


def run(days: int, root: Path, with_claude: bool, model: str) -> dict:
    now = datetime.now().astimezone()
    sessions = scan(root, now - timedelta(days=days))
    report = analyze(sessions, read_settings(), days, now)
    if with_claude:
        report["review"] = claude_review(report, sessions, model)
    return report


def print_report(report: dict, path: Path | None) -> None:
    st = report["stats"]
    print(f"Claude Code insights · last {report['days']} days · {st['sessions']} sessions, {st['prompts']} prompts, "
          f"{st['outputTokens'] / 1e6:.1f}M output / {st['cacheReadTokens'] / 1e6:.0f}M cache-read tokens")
    for f in report["findings"]:
        print(f"\n[{f['severity']:<6}] {f['title']}\n         {f['evidence']}\n      →  {f['fix']}")
    rv = report.get("review")
    if rv:
        print("\n" + (rv["markdown"] if rv["ok"] else f"(claude review failed: {rv['error']})"))
    if path:
        print(f"\nsaved {path}")


# ---------- Windows Task Scheduler ----------

def install_schedule(at: str, model: str, dry: bool) -> None:
    """Mon–Fri at `at`, via wsl.exe so WSL starts if it is not running; a missed run (PC off or
    asleep) runs as soon as possible afterwards. conhost --headless keeps the console hidden."""
    import app
    if not app.is_wsl():
        raise SystemExit("--install-schedule needs WSL (Windows Task Scheduler)")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        raise SystemExit("--at expects HH:MM")
    distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu")
    log = ledger.PATH.parent / "insights" / "run.log"
    sh = f"mkdir -p {log.parent} && {{ date; {sys.executable} {HERE / 'insights.py'} --claude --model {model}; }} >> {log} 2>&1"
    args = f"wsl.exe -d {distro} --cd ~ -- bash -lc \"{sh}\""
    script = f"""
$a = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument {app.ps_str('--headless ' + args)}
$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At {app.ps_str(at)}
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName {app.ps_str(TASK)} -Action $a -Trigger $t -Settings $s -Description 'Claude Code insights report (claude-telemetry-dashboard/insights.py)' -Force | Out-Null
(Get-ScheduledTaskInfo -TaskName {app.ps_str(TASK)}).NextRunTime.ToString('yyyy-MM-dd HH:mm')
"""
    out = app.powershell(script, dry)
    if not dry:
        if not re.search(r"\d{4}-\d\d-\d\d", out):
            raise SystemExit(f"registering the task failed:\n{out}")
        print(f"scheduled \"{TASK}\" Mon–Fri {at}, next run {out.splitlines()[-1]}\nlog: {log}")


def uninstall_schedule(dry: bool) -> None:
    import app
    app.powershell(f"Unregister-ScheduledTask -TaskName {app.ps_str(TASK)} -Confirm:$false -ErrorAction SilentlyContinue", dry)
    if not dry:
        print(f"removed \"{TASK}\"")


def schedule_status() -> None:
    import app
    print(app.powershell(f"""
$t = Get-ScheduledTask -TaskName {app.ps_str(TASK)} -ErrorAction SilentlyContinue
if (-not $t) {{ 'not scheduled'; exit }}
$i = $t | Get-ScheduledTaskInfo
"state: $($t.State)  next: $($i.NextRunTime)  last: $($i.LastRunTime)  result: $($i.LastTaskResult)"
""", False) or "not scheduled")
    rep = latest()
    print(f"latest report: {rep['generatedAt'] if rep else 'none'} ({DIR / 'latest.json'})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=DAYS, help=f"look-back window (default {DAYS})")
    ap.add_argument("--projects-dir", type=Path, default=PROJECTS_DIR)
    ap.add_argument("--claude", action="store_true", help="add written recommendations from `claude -p`")
    ap.add_argument("--model", default=CLAUDE_MODEL, help=f"model for --claude (default {CLAUDE_MODEL})")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--no-save", action="store_true", help="do not write the report files")
    ap.add_argument("--install-schedule", action="store_true", help="run Mon–Fri via Windows Task Scheduler")
    ap.add_argument("--at", default="07:30", help="time for --install-schedule (HH:MM, default 07:30)")
    ap.add_argument("--uninstall-schedule", action="store_true")
    ap.add_argument("--schedule-status", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="with the schedule options: print, change nothing")
    args = ap.parse_args()

    if args.install_schedule:
        return install_schedule(args.at, args.model, args.dry_run)
    if args.uninstall_schedule:
        return uninstall_schedule(args.dry_run)
    if args.schedule_status:
        return schedule_status()
    report = run(args.days, args.projects_dir, args.claude, args.model)
    path = None if args.no_save else save(report)
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print_report(report, path)


if __name__ == "__main__":
    sys.exit(main())
