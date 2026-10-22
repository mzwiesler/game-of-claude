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
python3 -m unittest test_collect test_insights test_pokesave  # tests
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
python3 insights.py --install-schedule  # Windows Task Scheduler, Mon–Fri 07:30 with --claude (--at HH:MM)
python3 insights.py --schedule-status | --uninstall-schedule
python3 -m unittest test_insights
```

Reports: `~/.local/share/claude-telemetry/insights/<date>.json` and `latest.json` (60 kept), run log
`run.log` next to them. The task starts WSL itself via `wsl.exe` (hidden console) and catches up a
missed run when the PC was off or asleep at 07:30.

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

Level *L* needs 250·(L−1)² XP. Levels bring titles and unlocks (cape, glowing blade, battle sounds,
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
- **Level up and evolve**: wins and catches give your partner EXP (Lv³ curve, 1/25 of the games'
  battle EXP since a battle ends every few seconds: the first evolution at Lv 16 takes about three
  hours of Claude work); real XP counts 1:1. It evolves at its level; stone evolutions happen at Lv 30, trade evolutions at Lv 36, and Eevee picks Vaporeon,
  Jolteon or Flareon at random. Partners can't grow past the level cap, 15 + 5 × trainer level.
- **Catch**: a weakened wild Pokémon that isn't in your Pokédex yet gets up to three balls (Poké Ball,
  Great Ball from trainer LV 5, Ultra Ball from LV 12). Rarer and evolved Pokémon break free more often.
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
- `server.py`: HTTP server (`/`, `/game.js`, `/poke.js`, `/api/stats`, `/api/events`, `/healthz`) and `--export`
- `index.html`: the dashboard (vanilla JS, inline SVG charts)
- `game.js`: arena, hero, enemies and character sheet (D&D theme, plus the shared arena styles)
- `poke.js`: the Pokémon theme: partner, wild Pokémon, catching, evolution, Pokédex
- `pokesave.py`: the Pokémon save on disk (`pokemon.json` next to the ledger), merged on every write
- `app.py`: desktop window launcher, background server, Windows shortcut (`claude-telemetry.ico`)
- `test_collect.py`: tests
