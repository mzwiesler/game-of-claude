# Security scans — design

Date: 2026-10-23 · Status: draft for review

## Intent

The user runs Claude Code heavily on their **company machine** (WSL2 on Windows, Liebherr network,
Atlassian / Microsoft 365 / Terraform MCP servers attached). They want the dashboard to answer two
questions they cannot answer today:

1. **Did Claude get to see something it should not have?** Everything Claude reads — a file, a
   command's output, a Confluence page, an MCP result, a pasted prompt — becomes part of the
   conversation and is sent to Anthropic. The sandbox only limits what commands can touch; it says
   nothing about what ended up in the context. The transcripts in `~/.claude/projects/**.jsonl` are
   exactly that context, so they are the evidence.
2. **Did Claude do, or could it have done, something that harms the company?** Writes outside the
   projects, unexpected network access, sandbox escapes, and actions that leave the machine in the
   user's name: `git push`, Jira/Confluence writes, Terraform runs, mail drafts, uploads.

Plus the **posture** that bounds both: how tight sandbox and permissions are, which MCP servers,
plugins and hooks are active.

Success: a short answer the user trusts — "all clear" or "look at these 3 things" — with enough
evidence to jump to the session and judge it. Not a wall of alarms.

## Goals

- A new `security.py` (stdlib only, like the rest) that scans the last N days of transcripts plus the
  settings files and writes a report; a **Security** card in the dashboard that shows it.
- Three groups of checks: **posture**, **events** (what happened), **secrets** (what leaked into the
  context). Listed in detail below.
- Every finding names the session (project, time, `claude --resume <id>` copy button like the
  Needs-attention rows) so the user can check it.
- Show which checks **passed** too, so "all clear" means something.

## Non-goals (v1)

- Blocking anything live. No PreToolUse hooks, no changes to settings. The scan only reports;
  the fix text says what setting to change.
- Scanning the codebase or dependencies (SAST, CVEs). This is about Claude's behaviour, not the code.
- Scanning anything outside what Claude Code saw: no browser history, no system logs.
- Company source code is assumed fine to send to Claude (the user uses Claude on it daily);
  code by itself is never a finding. *(Assumption — see open questions.)*

## Anti-goals (failure even if it works)

- **The scan itself leaks.** The report must never contain a full secret: mask to the first 4 and
  last 2 characters plus length and kind. No `--claude` review for security, nothing is sent to
  Claude or anywhere else. `server.py --export` (the "mail it around" snapshot) leaves the security
  report out.
- **Alarm fatigue.** If the card is red every day because of the same known thing, the user stops
  looking. Hence: severities with clear rules, low findings folded, an "I reviewed this" acknowledge
  per finding, and dedupe of repeated events.
- **False confidence.** Matches must come from actual `tool_use` / `tool_result` / prompt content,
  never from system prompts or tool descriptions: the transcripts contain the sandbox instructions
  verbatim ("Operation not permitted", `<sandbox_violations>`, `dangerouslyDisableSandbox`), and a
  naive grep counts those (seen while exploring: thousands of false hits).

## How it fits the existing code (decided)

- Mirror `insights.py`: `scan(root, since)` → `analyze(sessions, settings, days, now)` → `save()` to
  `ledger.PATH.parent / "security" / <date>.json` + `latest.json` (60 kept) → `latest()` cached by mtime.
  Same `finding()` shape (`id, kind, severity, title, evidence, fix`), plus `sessions: [{id, project, at}]`
  (up to 5) and a stable `fp` fingerprint for acknowledging.
- Reuse `collect._ts`, `PROJECTS_DIR`, `CLAUDE_DIR`, and `insights._repo_root`, `_cmd_key`, `top`,
  `read_settings` instead of copying them. A separate scan pass is fine (security needs tool inputs
  and results that `insights.scan` throws away); if a shared pass falls out naturally, the builder may do it.
- CLI: `python3 security.py [--days 7] [--json] [--no-save]`, printing like `insights.print_report`.
- Server: `snap["security"] = security.latest()` (minus acknowledged findings flagged, not dropped),
  `POST /api/security/refresh` (runs the scan in a thread, one at a time; local only, no cost) and
  `POST /api/security/ack` with body `{fp}` / `{fp, undo: true}`; both need the `X-Game-Of-Claude: 1`
  header like the existing POSTs. Acks live in `security/acks.json`.
- The existing scheduled insights task (`insights.py --install-schedule`) also runs the security scan
  afterwards, so the morning report covers both. No separate schedule.
- Dashboard: a **Security** card next to Insights, same row/fold styling (`frow sev-*`, `details.more`).
  Header: status dot red (any unacknowledged high) / yellow (medium) / green, "All clear" or
  "N things to look at", last scan time, ↻ button. Body: findings grouped Leaks · Events · Posture,
  each with evidence, fix, session refs with resume copy, and an "✓ reviewed" button; acknowledged
  findings move into a folded "reviewed" list. A folded "N checks passed" list at the end.
  Toast + desktop note (existing `notifyOn`) when a new report has an unacknowledged high finding.
- Tests: `test_security.py` in the style of `test_insights.py` (synthetic transcripts in a temp dir),
  added to the README test command. README gets a "Security" section.

## The checks

Severity rules: **high** = something sensitive likely reached Claude, or something risky actually
happened outside the sandbox / to company systems.

**Who approved it matters** (decided): each tool call's record carries `permissionDecision`
(`source: config` + `reasonType: classifier` = auto mode; `reasonType: mode` = permission mode;
`source: user_temporary|user_permanent` = the user by hand; allow rules). A risky command is **high**
only when the user approved it by hand or an allow rule let it through, or it ran unsandboxed *and*
was approved that way. Auto-mode / mode approvals make it **medium**. Always **high** regardless of
approver: any secret or credential file that reached Claude, and any write to a production target.
"Blocked → re-run unsandboxed" (check 5) follows the same rule. This keeps red rare. **medium** = risky capability that is open, or a
risky action that was blocked/asked. **low** = worth knowing (inventory, hygiene).

### A. Leaks — what reached Claude

Scanned text: user prompts, `tool_use` inputs, and `tool_result` contents (main sessions and
subagents). Each hit records channel (prompt / tool input / tool output + tool name), session, time.

1. **Secrets** (high). Patterns at least: Anthropic `sk-ant-…`, OpenAI-style `sk-…`, GitHub
   `ghp_/gho_/ghs_/github_pat_`, AWS `AKIA…`, Azure storage `AccountKey=` and SAS `sig=`,
   connection strings with `Password=`/`pwd=`, PEM private key headers, JWTs (`eyJ….….…`), Slack
   `xox[bp]-`, Atlassian API tokens `ATATT…`, Databricks `dapi…`, Terraform Cloud `….atlasv1.…`.
   Generic `(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*<8+ non-space>` as **medium**
   (lower confidence). Skip obvious placeholders (`xxx`, `<token>`, `${VAR}`, `$VAR`, `***`,
   `changeme`, `example`). Dedupe by hash of the value; evidence shows masked value, kind, how many
   times, in which channels.
2. **Credential files read** (high if the read succeeded, medium if blocked/denied): Read/Grep/Glob
   paths or Bash commands touching `~/.ssh/`, `~/.aws/`, `~/.azure/`, `~/.kube/config`,
   `~/.docker/config.json`, `~/.netrc`, `~/.git-credentials`, `~/.config/gh/hosts.yml`, `*.pem`,
   `*.key`, `*.pfx`, `id_rsa*`, `.env` / `.env.*` (not `.env.example`), `~/.zshrc.local*`,
   Windows credential stores (`cmdkey`, `Get-StoredCredential`, `/mnt/c/Users/*/AppData/**/Credentials`).
   Also environment dumps: bare `env`, `printenv`, `set` (no args) whose output reached Claude.
3. **Files outside the project** (low; medium when under `/mnt/c/Users/…` or another user's home):
   Read/Grep/Glob of paths outside the session's repo root, `~/.claude`, `/tmp`, `$TMPDIR` and
   system/tool dirs (`/usr`, site-packages, `node_modules`). Grouped by top directory.
4. **Personal / customer data** (medium): IBANs, credit card numbers (Luhn-checked). Nothing broader
   in v1 *(see open questions)*.

### B. Events — what Claude did

5. **Sandbox escapes** (medium; high when the same session got a sandbox block for that command just
   before, i.e. "blocked → re-run unsandboxed"): Bash with `dangerouslyDisableSandbox`, grouped by
   `_cmd_key`, plus whether it touched network or wrote outside the project. Excluded commands
   (`sandbox.excludedCommands`, e.g. `powershell.exe *`) count as unsandboxed too — they run on the
   Windows host with no sandbox at all.
6. **Sandbox blocks** (low; medium for hosts outside `allowedDomains` that are not package/registry
   hosts): prefer the structured `sandboxed` / `sandboxViolations` fields the records already carry
   (e.g. `{"kind": "network", "host": …, "port": …}`); fall back to the `<sandbox_violations>` block inside **tool_result** content, lines like
   `deny network-outbound api.anthropic.com:443` and file denies. Show hosts and paths with counts —
   this is what Claude tried to reach.
7. **Risky commands** (severity per "Who approved it matters" above): `curl|wget … | sh/bash`,
   `sudo`, `rm -rf` on absolute/home paths, `chmod -R 777`, `git push --force`/`-f`, `git push` to
   `main`/`master`, `git reset --hard` + push, `terraform apply/destroy`, `kubectl delete/apply`,
   `az … delete`, `DROP TABLE/DATABASE`, history rewrites. Uploads / exfil channels: `scp`, `rsync`
   to a remote, `curl -T`/`--data @file`/`-F …=@`, `gh gist create`, `nc`, `base64 … | curl`.
8. **Actions in your name** (low as inventory; **high** for production targets): everything that left the machine —
   `git push`, `gh pr create/merge/comment`, `gh issue create`, and MCP tools whose name has a write
   verb (`create|update|delete|add|transition|send|post|upload|comment|merge|apply|run|cancel`).
   Grouped per server: "Jira: 11 issues created, 3 comments; Confluence: 0 writes". A write to a
   **production target** is **high**. Production targets = a constant `PROD` list of substrings
   (default `("prod", "prd", "production")`) matched against MCP server names (e.g. `terraform-prod`)
   and Terraform workspace names in tool inputs. *(My call: a list rather than a hard-coded
   substring, so it can grow; git branches and Jira projects are not production targets in v1.)*
9. **Prompt-injection exposure** (medium): in one session, untrusted content came in (WebFetch,
   WebSearch, browser MCP `navigate_page`/`new_page`, reading a downloaded file) and within the next
   ~10 tool calls a check-7 or check-8 action followed. Evidence names the source URL/host and the action.
10. **Permission mode** (high for any session in `bypassPermissions`; low summary otherwise): from the
    records' `permissionMode` field. Currently nearly all sessions run in `auto`.

### C. Posture — how much could go wrong

Read `~/.claude/settings.json`, and for each repo root seen in the window its `.claude/settings.json`
and `.claude/settings.local.json` and `.mcp.json`; also managed settings
(`/etc/claude-code/managed-settings.json`) if present. Report which file a finding comes from.

11. **Sandbox** — `enabled` false (high); `allowUnsandboxedCommands: true` (medium: the escape hatch is
    open, auto mode decides alone); `excludedCommands` (medium per entry, high if also in `permissions.allow`);
    `network.allowedDomains` containing `*` (high) or general upload hosts like `github.com`,
    `*.githubusercontent.com`, pastebins (low, "exfil channel"); `filesystem.allowWrite` covering `~` or `/` (high).
    Passed checks: credentials denied (`sandbox.credentials`), `denyRead` present.
12. **Permissions** — broad allow rules: `Bash(*)`, `Bash` alone, interpreters/shells/network tools
    (`python*`, `node`, `bash`, `sh`, `curl`, `wget`, `ssh`, `scp`, `powershell*`) (medium); MCP write
    tools in `allow`, so they run without asking (medium, e.g. `jira_add_comment`, `jira_transition_issue`);
    `defaultMode: bypassPermissions` or `skipDangerousModePermissionPrompt: true` (high);
    `Edit(~/.claude/settings.json)` deny present (passed check).
13. **Extensions** — inventory of enabled plugins and MCP servers with their source marketplace;
    plugins from marketplaces other than official / the company's own (`claude-plugins-official`,
    `builtin`, `lwe`, `werkbank` — list kept as a constant) are medium. Hooks whose command fetches
    remote code (`curl|wget … | sh`, `npx <pkg>@latest`, `uvx`) are medium.

## Left to the builder

- Exact regexes, thresholds for "repeated", and the fingerprint format (stable across runs:
  kind + normalised subject, e.g. `secret:<sha256[:12]>`, `escape:<cmd_key>`).

## Acknowledging (decided, my call)

An ack records the fingerprint, when it was made, the session ids it covered and the severity.
A finding stays reviewed only while it has no new session and its severity has not risen; a new
occurrence reopens it (the card shows "came back"). A secret's fingerprint is its value hash, so
the same leaked token does not reopen once rotated-and-acked unless it appears in a new session.
- Whether security shares one transcript pass with insights.
- Card layout details within the existing visual language; which report fields go in a stats line.
- Performance: the transcript dir is ~0.5 GB; only files touched in the window are read (like
  `insights.scan`). Keep a scan under ~30 s.

## Calls I made (not discussed with the user)

- Look-back 7 days default (`--days`), same as insights.
- Separate card, not more findings inside Insights.
- Acknowledge button in v1 (against alarm fatigue).
- Security report excluded from `--export`.
- No Claude review for this report.
- Runs with the existing scheduled task + on demand; not on every server refresh.

## Open questions for the user

- Which data classes beyond secrets worry them (personal data, customer data, contracts, HR)?
  Not answered yet; v1 ships check 4 as IBAN + credit card only, and treats source code as fine.
