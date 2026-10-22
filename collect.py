"""Collects Claude Code telemetry from the local transcripts (~/.claude/projects/**/*.jsonl).

Every Claude Code session writes one JSONL file. Assistant records carry the model and the
API usage (tokens), user records the prompts, tool_use blocks the tool calls. Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import game
import ledger as ledger_mod

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
PROJECTS_DIR = CLAUDE_DIR / "projects"

ATTENTION_WINDOW = 3600  # seconds since the last record for a session to count as open
LEDGER_EVERY = 30  # seconds between ledger writes at most (Collector.save)

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def _is_prompt(rec: dict) -> bool:
    """A real user prompt: text typed by the user, not a tool result or injected meta message."""
    if rec.get("isMeta") or rec.get("isSidechain"):
        return False
    content = rec.get("message", {}).get("content")
    if isinstance(content, str):
        return not content.startswith("<")  # <command-name>, <local-command-stdout>, …
    if isinstance(content, list):
        return any(b.get("type") == "text" for b in content) and not any(b.get("type") == "tool_result" for b in content)
    return False


def new_game_view() -> dict:
    """What the game counts of a session: only records at or after the game start (Collector.start).
    The ledger stores exactly this, game.state reads only this."""
    return {"prompts": 0, "xp": Counter(), "tokens": Counter(), "hours": Counter(), "days": defaultdict(Counter),
            "models": set(), "start": None, "end": None, "feats": []}


def new_session(path: Path, since: datetime | None = None) -> dict:
    return {
        "file": str(path), "sessionId": path.stem, "subagent": "subagents" in path.parts,
        "title": None, "cwd": None, "branch": None, "version": None, "start": None, "end": None,
        "prompts": 0, "turns": 0, "tokens": Counter(), "models": defaultdict(Counter), "tools": Counter(),
        "hours": Counter(), "days": defaultdict(Counter), "errors": 0,
        "last": None, "lastPrompt": None, "lastTool": None,  # last main-chain record, for the attention status
        "g": new_game_view(), "_since": since,  # game counters (game.py), since=None counts everything
        "_offset": 0, "_ino": None, "_seenMsgs": set(), "_seenTools": set(), "_toolNames": {}, "_failed": set(),
    }


# Bash commands that count as game events (game.py), checked in this order
BASH_EVENTS = (
    ("pr", re.compile(r"\bgh\s+pr\s+create\b")),
    ("commit", re.compile(r"\bgit\s+commit\b")),
    ("deploy", re.compile(r"\b(terraform\s+apply|kubectl\b[^|;&]*\s(apply|rollout)|helm\s+(upgrade|install)|docker\s+push)\b")),
    ("test", re.compile(r"\b(pytest|unittest|(npm|pnpm|yarn)\s+(run\s+)?test|go\s+test|cargo\s+test|dotnet\s+test|jest|vitest|mvn\s+test|gradle\w*\s+test)\b")),
)
FEATS = {"pr", "commit", "deploy", "test", "bugfix"}  # shown in the battle log


def tool_event(name: str, inp: dict) -> str:
    if name == "Bash":
        cmd = str(inp.get("command", ""))
        return next((ev for ev, rx in BASH_EVENTS if rx.search(cmd)), "tool")
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "edit"
    if name in ("Agent", "Task"):
        return "agent"
    if name in ("WebFetch", "WebSearch"):
        return "web"
    if name.startswith("mcp__"):
        return "mcp"
    return "tool"


def _xp(g: dict | None, ev: str, day: str | None, ts: datetime | None) -> None:
    if g is None:  # before the game start
        return
    g["xp"][ev] += 1
    if day:
        g["days"][day]["xp_" + ev] += 1
    if ev in FEATS and ts:
        g["feats"] = (g["feats"] + [(ts, ev)])[-6:]  # the latest notable ones, for the battle log


def feed(s: dict, path: Path, st: os.stat_result) -> bool:
    """Parses only the bytes appended since the last call (transcripts are append-only). A file
    that shrank or was replaced is parsed again from the start. Returns True if records were read."""
    if st.st_ino != s["_ino"] or st.st_size < s["_offset"]:
        since = s.get("_since")
        s.clear()
        s.update(new_session(path, since))
        s["_ino"] = st.st_ino
    if st.st_size == s["_offset"]:
        return False
    try:
        with path.open("rb") as fh:
            fh.seek(s["_offset"])
            data = fh.read()
    except OSError:
        return False
    end = data.rfind(b"\n") + 1  # keep a half-written last line for the next round
    if not end:
        return False
    s["_offset"] += end
    for line in data[:end].splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        _record(s, rec)
    return True


def _record(s: dict, rec: dict) -> None:
    """Assistant messages are split into one record per content block with the usage repeated,
    so usage is counted once per message id."""
    typ = rec.get("type")
    if typ == "ai-title" or typ == "summary":
        s["title"] = rec.get("aiTitle") or rec.get("title") or rec.get("summary") or s["title"]
        return
    if typ not in ("user", "assistant"):
        return
    ts = _ts(rec.get("timestamp"))
    if ts:
        s["start"] = min(s["start"] or ts, ts)
        s["end"] = max(s["end"] or ts, ts)
    since = s["_since"]
    g = s["g"] if since is None or (ts and ts >= since) else None  # counts for the game
    if g and ts:
        g["start"] = min(g["start"] or ts, ts)
        g["end"] = max(g["end"] or ts, ts)
    s["cwd"] = s["cwd"] or rec.get("cwd")
    s["branch"] = rec.get("gitBranch") or s["branch"]
    s["version"] = rec.get("version") or s["version"]
    day = ts.strftime("%Y-%m-%d") if ts else None
    msg = rec.get("message") or {}
    content = msg.get("content")
    if not rec.get("isSidechain") and not rec.get("isMeta"):
        tools = [b.get("name") for b in content or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
        s["last"] = {"type": typ, "stop": msg.get("stop_reason"), "tool": tools[-1] if tools else None, "at": ts}
        if typ == "user" and "[Request interrupted by user" in json.dumps(content):
            s["last"]["stop"] = "interrupted"  # Esc: Claude stopped and waits for the user

    if typ == "user":
        if _is_prompt(rec):
            text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content if b.get("type") == "text")
            s["lastPrompt"] = " ".join(text.split())[:160]
            s["prompts"] += 1
            if ts:
                s["hours"][ts.hour] += 1
            if day:
                s["days"][day]["prompts"] += 1
            if g:
                g["prompts"] += 1
                if ts:
                    g["hours"][ts.hour] += 1
                if day:
                    g["days"][day]["prompts"] += 1
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            name = s["_toolNames"].pop(b.get("tool_use_id"), None)
            if b.get("is_error"):
                s["errors"] += 1
                s["_failed"].add(name)
            elif name in s["_failed"]:  # failed, then the same tool worked: a bug slain
                s["_failed"].discard(name)
                _xp(g, "bugfix", day, ts)
        return

    for b in content or []:
        if b.get("type") == "tool_use" and b.get("id") not in s["_seenTools"]:
            s["_seenTools"].add(b.get("id"))
            name = b.get("name", "?")
            s["_toolNames"][b.get("id")] = name
            if not rec.get("isSidechain"):
                s["lastTool"] = name
            _xp(g, tool_event(name, b.get("input") or {}), day, ts)
            if name.startswith("mcp__"):  # mcp__server__tool → mcp:server
                name = "mcp:" + name.split("__")[1]
            s["tools"][name] += 1
            if day:
                s["days"][day]["tools"] += 1
    mid = msg.get("id") or rec.get("uuid")
    usage = msg.get("usage")
    model = msg.get("model")
    if mid in s["_seenMsgs"] or not usage or not model or model == "<synthetic>":
        return
    s["_seenMsgs"].add(mid)
    s["turns"] += 1
    for k in TOKEN_KEYS:
        v = usage.get(k) or 0
        s["tokens"][k] += v
        s["models"][model][k] += v
    s["models"][model]["turns"] += 1
    if day:
        s["days"][day]["turns"] += 1
        s["days"][day]["output_tokens"] += usage.get("output_tokens") or 0
        s["days"][day]["tokens"] += sum(usage.get(k) or 0 for k in TOKEN_KEYS)
    if g:
        for k in TOKEN_KEYS:
            g["tokens"][k] += usage.get(k) or 0
        g["models"].add(model)
        if day:
            g["days"][day]["output_tokens"] += usage.get("output_tokens") or 0


def parse_file(path: Path) -> dict:
    """Parses one whole transcript into a per-session summary."""
    s = new_session(path)
    try:
        feed(s, path, path.stat())
    except OSError:
        pass
    return s


def status(s: dict, now: datetime) -> str:
    """waiting = Claude ended its turn and waits for the user; approval = a tool call has been
    pending for a while (usually a permission prompt); working = Claude is busy."""
    last = s["last"]
    if not last:
        return "idle"
    if last["stop"] == "interrupted":
        return "waiting"
    if last["type"] == "assistant":
        if last["tool"]:
            age = (now - last["at"]).total_seconds() if last["at"] else 0
            return "approval" if age > 30 else "working"
        if last["stop"] in ("end_turn", "stop_sequence", "max_tokens", "refusal", None):
            return "waiting"
    return "working"


class Collector:
    """Keeps one parsed session per transcript and reads only what was appended since the last
    refresh. A scan of ~400 files costs a few ms, so refresh() can run every second.

    The game only counts what happened since self.start (stored in the ledger; a missing or
    corrupt ledger or new_game() starts a new game now). The ledger (ledger.py) keeps the game
    view of every transcript seen, so the XP of transcripts Claude Code has deleted still
    counts ("archived"). ledger=None keeps it in memory only. Summaries are taken lazily:
    refresh() only marks grown files dirty, save() and a file's deletion turn them into entries."""

    def __init__(self, root: Path = PROJECTS_DIR, ledger: Path | None = ledger_mod.PATH):
        self.root = root
        self.cache: dict[str, dict] = {}
        self.ledger_path = ledger
        self.start, self.ledger = ledger_mod.load(ledger) if ledger else (None, {})
        self._dirty: set[str] = set()  # live files whose ledger entry is outdated
        self._unsaved = self.start is None  # ledger changed since the last write
        self._saved = 0.0  # time.monotonic() of the last write
        self.start = self.start or datetime.now().astimezone()

    def new_game(self, at: datetime | None = None) -> None:
        """Back to level 1: the game counts only what happens from now (or at) on. The old
        ledger is kept as <name>.<time>.bak and all transcripts are parsed again."""
        if self.ledger_path and self.ledger_path.exists():
            bak = self.ledger_path.with_name(f"{self.ledger_path.name}.{datetime.now():%Y%m%d-%H%M%S}.bak")
            os.replace(self.ledger_path, bak)
        self.start = at or datetime.now().astimezone()
        self.cache, self.ledger, self._dirty, self._unsaved = {}, {}, set(), True

    def _keep(self, k: str) -> None:
        """Ledger entry from the live session; sessions without game activity need none."""
        e = ledger_mod.summary(self.cache[k])
        if e["prompts"] or e["xp"] or e["tokens"]:
            self.ledger[k] = e
        else:
            self.ledger.pop(k, None)

    def refresh(self) -> bool:
        """Picks up new, grown and deleted transcripts. Returns True if anything changed."""
        changed, alive = False, set()
        for p in self.root.rglob("*.jsonl"):
            try:
                st = p.stat()
            except OSError:
                continue
            key = str(p)
            alive.add(key)
            s = self.cache.get(key)
            if s is None:
                s = self.cache[key] = new_session(p, self.start)
            if feed(s, p, st):
                changed = True
                self._dirty.add(key)
        for k in set(self.cache) - alive:
            if k in self._dirty:  # last chance to keep its XP
                self._dirty.discard(k)
                self._keep(k)
                self._unsaved = True
            del self.cache[k]
            changed = True
        return changed

    def save(self, force: bool = False) -> bool:
        """Writes the ledger if anything changed, at most every LEDGER_EVERY seconds unless
        forced (shutdown, --export). Returns True if it was written."""
        if not (self._dirty or self._unsaved) or not force and time.monotonic() - self._saved < LEDGER_EVERY:
            return False
        for k in self._dirty:
            self._keep(k)
        self._dirty.clear()
        self._unsaved = True
        self._saved = time.monotonic()
        if not self.ledger_path:
            self._unsaved = False
            return False
        try:
            ledger_mod.save(self.ledger_path, self.start, self.ledger)
        except OSError as e:  # retried on the next save
            print(f"ledger: cannot write {self.ledger_path}: {e}", file=sys.stderr, flush=True)
            return False
        self._unsaved = False
        return True

    def archived(self) -> list[dict]:
        """Ledger entries of this root's transcripts that are gone from disk. Files on disk always
        count from the live parse, never from their ledger copy."""
        prefix = str(self.root).rstrip(os.sep) + os.sep
        return [e for k, e in self.ledger.items() if k not in self.cache and k.startswith(prefix)]

    def sessions(self) -> list[dict]:
        return list(self.cache.values())

    def attention_sig(self) -> tuple:
        """Status of the open sessions. Changes without new records (approval after 30 s, a
        session leaving the one-hour window), so the server checks it on every tick."""
        now = datetime.now().astimezone()
        return tuple(sorted((s["sessionId"], status(s, now)) for s in self.cache.values()
                            if not s["subagent"] and s["end"] and (now - s["end"]).total_seconds() < ATTENTION_WINDOW))

    def snapshot(self, days: int = 30, refresh: bool = True) -> dict:
        if refresh:
            self.refresh()
        sess = self.sessions()
        main = [s for s in sess if not s["subagent"] and s["start"]]
        now = datetime.now().astimezone()
        today = now.strftime("%Y-%m-%d")

        tokens, tools, hours, models = Counter(), Counter(), Counter(), defaultdict(Counter)
        daily, projects = defaultdict(Counter), defaultdict(Counter)
        for s in sess:
            tokens.update(s["tokens"])
            tools.update(s["tools"])
            hours.update(s["hours"])
            for m, c in s["models"].items():
                models[m].update(c)
            for d, c in s["days"].items():
                daily[d].update(c)
            proj = s["cwd"] or "?"
            projects[proj]["tokens"] += sum(s["tokens"].values())
            projects[proj]["output_tokens"] += s["tokens"]["output_tokens"]
            projects[proj]["prompts"] += s["prompts"]
            projects[proj]["tools"] += sum(s["tools"].values())
        for s in main:
            daily[s["start"].strftime("%Y-%m-%d")]["sessions"] += 1
            projects[s["cwd"] or "?"]["sessions"] += 1

        day_keys = sorted(daily)[-days:]
        active = [s for s in main if s["end"] and (now - s["end"]).total_seconds() < 600]
        cache_in = tokens["cache_read_input_tokens"] + tokens["cache_creation_input_tokens"] + tokens["input_tokens"]
        home = str(Path.home())

        def short(p: str) -> str:
            return p.replace(home, "~", 1) if p else "?"

        recent = sorted(main, key=lambda s: s["end"], reverse=True)[:25]
        prio = {"approval": 0, "waiting": 1, "working": 2, "idle": 3}
        attention = sorted(
            (s for s in main if s["end"] and (now - s["end"]).total_seconds() < ATTENTION_WINDOW),
            key=lambda s: (prio[status(s, now)], -s["end"].timestamp()))
        return {
            "generatedAt": now.isoformat(timespec="seconds"),
            "game": game.state([{"subagent": s["subagent"], "title": s["title"], "cwd": s["cwd"], **s["g"]} for s in sess],
                               today, self.start, self.archived()),
            "source": short(str(self.root)),
            "files": len(sess),
            "kpi": {
                "sessions": len(main),
                "subagents": sum(1 for s in sess if s["subagent"]),
                "prompts": sum(s["prompts"] for s in sess),
                "turns": sum(s["turns"] for s in sess),
                "toolCalls": sum(tools.values()),
                "toolErrors": sum(s["errors"] for s in sess),
                "outputTokens": tokens["output_tokens"],
                "totalTokens": sum(tokens.values()),
                "cacheHit": tokens["cache_read_input_tokens"] / cache_in if cache_in else 0,
                "activeNow": len(active),
                "today": dict(daily.get(today, {})),
                "firstSeen": min((s["start"] for s in main), default=now).isoformat(timespec="seconds"),
            },
            "tokens": dict(tokens),
            "daily": [{"date": d, **daily[d]} for d in day_keys],
            "models": sorted(({"model": m, **c} for m, c in models.items()), key=lambda r: -r["output_tokens"]),
            "tools": tools.most_common(18),
            "hours": [hours.get(h, 0) for h in range(24)],
            "projects": sorted(({"path": short(p), **c} for p, c in projects.items()), key=lambda r: -r["tokens"])[:12],
            "sessions": [{
                "id": s["sessionId"], "title": s["title"], "project": short(s["cwd"]), "branch": s["branch"],
                "version": s["version"], "start": s["start"].isoformat(timespec="seconds"),
                "end": s["end"].isoformat(timespec="seconds"),
                "minutes": round((s["end"] - s["start"]).total_seconds() / 60, 1),
                "prompts": s["prompts"], "turns": s["turns"], "tools": sum(s["tools"].values()),
                "outputTokens": s["tokens"]["output_tokens"], "tokens": sum(s["tokens"].values()),
                "models": sorted(s["models"], key=lambda m: -s["models"][m]["output_tokens"]),
                "active": s in active,
            } for s in recent],
            "attention": [{
                "id": s["sessionId"], "title": s["title"], "project": short(s["cwd"]), "branch": s["branch"],
                "status": status(s, now), "tool": s["last"]["tool"] if s["last"] else None, "lastTool": s["lastTool"],
                "lastPrompt": s["lastPrompt"], "end": s["end"].isoformat(timespec="seconds"),
                "idleSec": int((now - s["end"]).total_seconds()),
                "models": sorted(s["models"], key=lambda m: -s["models"][m]["output_tokens"]),
            } for s in attention],
        }


if __name__ == "__main__":
    print(json.dumps(Collector().snapshot(), indent=2, default=str))
