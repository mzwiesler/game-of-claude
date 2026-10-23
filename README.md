# Game of Claude

Live dashboard for your local Claude Code usage, styled like a construction-site status board,
plus **Game of Claude**: a hero in the top-left arena who levels up with your work, as a
Dungeons & Dragons adventurer or a Pokémon trainer. Python stdlib only: no install step, and
nothing leaves your machine except the opt-in `insights.py --claude` review, which goes to Claude
like any other prompt (the Pokémon theme also loads its sprite images from GitHub).

```bash
python3 app.py                          # own desktop window (see below), starts the server if needed
python3 server.py                       # http://127.0.0.1:8765, opens the browser
python3 server.py --port 9000 --days 60 --no-browser
python3 server.py --export report.html  # static one-file snapshot (e.g. to mail around)
python3 collect.py                      # raw JSON
python3 server.py --new-game            # reset the hero to level 1 (old ledger is kept as backup)
python3 -m unittest test_collect test_insights test_pokesave test_security  # tests
```

## Insights (daily report)

`insights.py` looks at the last 7 days of sessions for optimisation potential and recurring work you
could automate, and the dashboard shows the newest report in the **Insights** card (low-severity
findings folded away, a toast when a new report arrives). Rules find friction that a setting, hook
or script removes for good: env prefixes retyped in Bash commands, sandbox bypasses, worktree-guard
refusals, failing hooks, `/mcp` reconnects, retries, missing tools, expired tokens, stale permission
allow entries, `.claude` files that drifted in worktrees, piling worktrees, requests that recur across
sessions (slash command / skill candidates), long and duplicated sessions. `--claude` adds written
recommendations from `claude -p` (Sonnet, no tools, no MCP, no saved session, ~20 s).
The **↻ Refresh** button in the card re-runs the analysis with the Claude review right away
(`POST /api/insights/refresh`, one run at a time; it needs a custom header, so other web pages
cannot trigger paid runs through the localhost server).

```bash
python3 insights.py                     # rules only, saves the report and prints it
python3 insights.py --claude            # plus Claude's recommendations
python3 insights.py --days 14 --json
python3 insights.py --install-schedule  # Windows Task Scheduler, Mon–Fri 07:30 with --claude, then security.py (--at HH:MM)
python3 insights.py --schedule-status | --uninstall-schedule
python3 -m unittest test_insights
```

Reports: `~/.local/share/claude-telemetry/insights/<date>.json` and `latest.json` (60 kept), run log
`run.log` next to them. The task starts WSL itself via `wsl.exe` (hidden console) and catches up a
missed run when the PC was off or asleep at 07:30.

## Security

`security.py` answers two questions about the last 7 days: did Claude get to see something it should
not have (everything it reads is sent to Anthropic as part of the conversation), and did it do, or
could it have done, something that harms the company. It scans the transcripts (only real prompts,
tool inputs and tool outputs: the system prompt and tool descriptions quote the sandbox texts and do
not count) plus `~/.claude/settings.json`, the managed settings and each seen repo's
`.claude/settings*.json` and `.mcp.json`. The dashboard shows the newest report in the **Security**
card: a status dot (red: open high finding, yellow: open medium, green: all clear), findings grouped
Leaks · Events · Posture with evidence, fix and the sessions (click to copy `claude --resume <id>`),
the checks that passed, and a toast / desktop note when a new report has an open high finding.

- **Leaks**: secrets (API keys, tokens, JWTs, private keys, connection-string passwords …), credential
  files read (`~/.ssh`, `~/.aws`, `.env`, …) and environment dumps, files outside the session's
  project, IBANs and card numbers.
- **Events**: commands outside the sandbox (grouped by network / writes outside the project / excluded
  commands), "blocked, then re-run outside the sandbox", hosts the sandbox blocked, risky commands
  (`curl | sh`, `sudo`, force push, `terraform apply`, uploads …), actions in your name (git, gh, MCP
  writes per server), writes to production targets, outward actions right after web reads, and
  `bypassPermissions` sessions.
- **Posture**: sandbox settings, broad or MCP-write allow rules, plugins from outside marketplaces,
  hooks that fetch remote code, and an inventory of plugins and MCP servers.

Severity: **high** means something sensitive likely reached Claude, or something risky happened that
you or an allow rule approved (auto-mode approvals make it medium); any secret or credential file
read and any production write is always high. **✓ reviewed** folds a finding away until it happens in
a new session or gets worse (it then shows "came back"). The report never holds a full secret (first
4 and last 2 characters plus length), nothing is sent anywhere, and `server.py --export` leaves it out.

```bash
python3 security.py                 # scan, save the report, print it (a few seconds)
python3 security.py --days 14 --json
python3 security.py --no-save
python3 -m unittest test_security
```

Reports: `~/.local/share/claude-telemetry/security/<date>.json` and `latest.json` (60 kept), reviews in
`acks.json` next to them. The scheduled insights task runs the scan right after the insights report;
**↻ Scan** in the card runs it now (`POST /api/security/refresh`, `POST /api/security/ack`, both with
the same custom header as the other POSTs). Production targets (`PROD`), trusted plugin marketplaces
and known registry hosts are constants at the top of `security.py`.

## Desktop window

`app.py` opens the dashboard as its own window: Microsoft Edge in app mode on the Windows host
(no tabs, no address bar, own taskbar entry), with a dedicated profile in
`%LOCALAPPDATA%\ClaudeTelemetry` (own notification permission and window position; delete it to
reset). Falls back to Chrome, then Chromium via WSLg, then the default browser
(`--browser auto|edge|chrome|wslg|default`).

```bash
python3 app.py                       # start server in the background if needed, open the window
python3 app.py --install-shortcut    # "Game of Claude" on the Desktop and in the Start menu
python3 app.py --status | --stop     # background server status / stop it
python3 app.py --uninstall-shortcut
python3 app.py --dry-run             # print what would run
```

The background server keeps running after the window closes (live data and notifications stay
current), until `--stop` or until WSL shuts down; the next launch starts it again (~4 s).
Log and pid file: `~/.local/state/claude-telemetry/server-<port>.{log,pid}`.

## Live updates

A watcher thread checks the transcripts every second (`--interval`). Transcripts are append-only,
so only the bytes added since the last check are parsed (~5 ms per check with ~400 files). A new
snapshot is pushed to the page via Server-Sent Events (`/api/events`) only when something changed,
including status changes without new records ("approval?" after 30 s), and at least once a minute.
The page swaps only the panels whose content changed; relative times tick in the browser.

**Needs attention** (top) lists sessions active in the last hour: *approval?* (a tool call pending
for more than 30 s, usually a permission prompt), *waiting for you* (Claude ended its turn or you
pressed Esc) and *working*. The tab title shows the count; **🔔 Notify** sends a desktop
notification when a session starts waiting while the tab is in the background; if the browser
blocks notifications the button shows "Blocked" with how to allow them. Independently of that,
the tab title blinks while a session waits for you and the window is not focused.

**Filters**: pick a repo (worktrees count as their main checkout) or a model in the filter bar, or
click a row in Projects / Models or a model pill. The header numbers, Activity, Token mix, Models,
Tools, Time of day, Projects and Recent sessions are then re-aggregated in the browser from
per-session counters in the snapshot (`facets`); Needs attention, Insights and Security stay
unfiltered. With a model filter, tokens and turns count that model only, prompts, tools and hours
count the sessions that used it. `?repo=~/repos/x&model=claude-opus-5-5` in the URL sets the filter.
Tools and Projects show the top 5 with **Show all**; Activity switches between 7, 14 and 30 days.
The filter, opened lists and range are remembered per browser.

## Game of Claude

The hero starts at level 1 when the game starts (first server start, or `--new-game`); only work
after that counts. Progress is saved in a ledger (`~/.local/share/claude-telemetry/ledger.json`,
`--ledger PATH` or `CLAUDE_TELEMETRY_LEDGER` to move it): written atomically when something
changed, at most every 30 s and on shutdown. When Claude Code deletes old transcripts, their XP
stays in the ledger, so levels never drop. A corrupt ledger is moved to `ledger.json.bak` and a
new game starts. XP per task (`game.py`):

| Task | XP | | Task | XP |
|---|---|---|---|---|
| Prompt | 5 | | Pull request (`gh pr create`) | 60 |
| Tool call | 1 | | Deploy (`terraform apply`, `kubectl apply`, `helm upgrade`, `docker push`) | 40 |
| Code edit (Edit/Write) | 3 | | Commit (`git commit`) | 25 |
| Web research | 2 | | Test run (pytest, npm test, go test, …) | 10 |
| MCP tool call | 3 | | Bug slain (a tool failed, then the same tool worked) | 8 |
| 1k output tokens | 1 | | Subagent sent | 8 |

Level *L* needs 125·(L−1)² XP. Levels bring titles and unlocks (cape, glowing blade, battle sounds,
shield, helmet, dragon familiar, critical hits, aura, twin blades, wings, lightning, crown) plus 15
achievements.

The arena (top left) is a Dungeons & Dragons-style dungeon that mirrors your live sessions:

- **Battle** (a session is working): the hero fights rotating foes from a 21-monster bestiary
  (giant rat, kobold, goblin, orc, skeleton, mimic chest, black knight, minotaur, troll, wraith,
  wyvern, floating eye, lich, red dragon, …). The tier follows the hero level; foe levels are
  random around it (☠ elites +5…+10). A new foe appears after each win or after 20–40 s; the tool
  Claude is using makes some foes more likely. Attacks roll a d20 (natural 20 = critical with the
  unlock, natural 1 = fumble). Real XP gains land as power strikes; big ones or a level-up summon
  the dragon boss.
- **The hero can lose**: foes hit back against the hero's AC (shield and helmet help), and at 0 HP
  the hero falls and respawns at the campfire. Defeats are cosmetic: they never cost real XP, and
  wins/losses are recorded per foe in the bestiary (browser storage).
- **Permission Gate** (a session needs your approval): a sealed portcullis with a red rune lock.
  **Idle** (sessions wait for you): "ORDERS?". **Rest** (nothing open): campfire.

Click the arena for the character sheet: ability scores, combat stats and W/L record, unlocks,
XP sources, battle log, achievements, bestiary and the sound toggle.

### Theme: Dungeons & Dragons or Pokémon

Switch with the selector in the character sheet, or open the dashboard with `?theme=pokemon`
(`?theme=dnd` switches back). The choice is stored per browser; D&D is the default.

In the **Pokémon** theme your real XP level is the *trainer* level, and the arena is a battle field:

- **Starter**: pick Bulbasaur, Charmander, Squirtle or Pikachu (Lv 5) in the trainer card.
- **Battle** (a session is working): wild Pokémon from the first 150 appear near your partner's
  level. Evolved forms only show up from their evolution level, legendaries (Articuno, Zapdos,
  Moltres, Mewtwo) from trainer LV 8 and Lv 50+. The tool Claude is using favours some types (shell:
  fire/fighting/rock/ground, edits: grass/normal/bug, reading: psychic/water/ice, web:
  flying/electric, agents: ghost/poison, MCP: electric/rock). Type matchups apply, and real XP gains
  land as "Claude power" hits.
- **Level up and evolve**: wins and catches give your partner EXP (Lv³ curve, 3/25 of the games'
  battle EXP since a battle ends every few seconds: the first evolution at Lv 16 takes about an
  hour of Claude work); real XP counts 3:1. It evolves at its level; stone evolutions happen at Lv 30, trade evolutions at Lv 36, and Eevee picks Vaporeon,
  Jolteon or Flareon at random. Partners can't grow past the level cap, 15 + 5 × trainer level.
- **Catch**: a weakened wild Pokémon that isn't in your Pokédex yet gets up to three balls (Poké Ball,
  Great Ball from trainer LV 5, Ultra Ball from LV 12). Rarer and evolved Pokémon break free more often.
- **Rarity**: every family has a tier, and evolved forms are rarer still. Rough average Claude work time
  until the first sighting: common (Pidgey, Rattata, Zubat, …) minutes; uncommon (Pikachu, Abra,
  Growlithe, Scyther, …) about an hour; rare (wild starters, Eevee, Dratini, Chansey, Ditto, fossils,
  Porygon) about 3 h; very rare (Snorlax, Lapras, Aerodactyl, Dragonite) 15–40 h; legendary birds about
  120 h; Mewtwo about 240 h. A level-up or a big XP gain lures out rarer ones for two minutes.
- **Your avatar**: the trainer card lists every caught Pokémon and the Pokédex (seen/caught); click
  one to make it your partner, the Pokémon in the arena.
- **Snorlax** blocks the path while a session waits for approval; **Pokémon Center** when nothing is
  open (or after your partner faints, which is cosmetic like the D&D defeats).

Pokémon progress is saved next to the XP ledger as `pokemon.json` (`pokesave.py`, via `/api/pokemon`),
so every browser shares it and clearing site data loses nothing; the browser keeps a copy for static
snapshots and while the server is down. Saves from several windows merge: no caught Pokémon is lost,
the copy with more EXP wins. Switching to the D&D theme freezes it as it is. Sprites are not part of this repo: they load
from the public [PokeAPI sprite repo](https://github.com/PokeAPI/sprites), with drawn placeholders
when GitHub is unreachable. Fan feature, not affiliated with Nintendo, Game Freak or The Pokémon Company.

## Data source

Claude Code writes every session as a JSONL transcript to `~/.claude/projects/<project>/<session>.jsonl`
(subagents under `<session>/subagents/`). `collect.py` reads them and aggregates:

| Panel | From |
|---|---|
| KPIs, token mix, models | `message.usage` of assistant records, counted once per message id |
| Tools | `tool_use` blocks (MCP tools grouped per server as `mcp:<server>`), errors from `tool_result.is_error` |
| Activity, time of day | prompt timestamps (user text, without tool results/meta/commands) |
| Projects, sessions | `cwd`, `gitBranch`, `ai-title` records |

Set `CLAUDE_CONFIG_DIR` or `--projects-dir` for another location. Claude Code deletes transcripts
after `cleanupPeriodDays` (default 30) days, so the charts only go back that far (XP is kept in
the ledger).

## Files

- `collect.py`: incremental transcript parser and aggregation (`Collector`)
- `game.py`: XP rules, levels, unlocks, achievements
- `ledger.py`: persisted XP ledger and game start
- `server.py`: HTTP server (`/`, `/game.js`, `/poke.js`, `/api/stats`, `/api/events`, `/healthz`, the insights / security POSTs) and `--export`
- `security.py`: security scan of transcripts and settings (Security card)
- `index.html`: the dashboard (vanilla JS, inline SVG charts)
- `game.js`: arena, hero, enemies and character sheet (D&D theme, plus the shared arena styles)
- `poke.js`: the Pokémon theme: partner, wild Pokémon, catching, evolution, Pokédex
- `pokesave.py`: the Pokémon save on disk (`pokemon.json` next to the ledger), merged on every write
- `app.py`: desktop window launcher, background server, Windows shortcut (`claude-telemetry.ico`)
- `test_collect.py`: tests
