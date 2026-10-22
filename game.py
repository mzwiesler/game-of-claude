"""Game of Claude: experience, levels, unlocks and achievements, derived from the transcripts.

Only what happened since the game start counts (a new game starts at level 1). Everything is
computed on every snapshot from the game views of the transcripts on disk plus the ledger
entries of transcripts Claude Code has deleted since (ledger.py, "archived"), so the hero
survives restarts and the transcript cleanup. The events are counted in collect.py
(new_game_view, tool_event, _xp).
"""
from __future__ import annotations

import heapq
from collections import Counter
from datetime import datetime, timedelta

# event: (xp, label). prompt and kilotoken come from the session counters, the rest from collect._xp
XP = {
    "prompt": (5, "Prompts given"),
    "tool": (1, "Tool calls"),
    "edit": (3, "Code edits"),
    "test": (10, "Test runs"),
    "commit": (25, "Commits"),
    "pr": (60, "Pull requests"),
    "deploy": (40, "Deployments"),
    "agent": (8, "Subagents sent"),
    "web": (2, "Web research"),
    "mcp": (3, "MCP tool calls"),
    "bugfix": (8, "Bugs slain"),
    "kilotoken": (1, "1k output tokens"),
}

LEVEL_XP = 250  # tuned so a busy day is worth roughly a third of a level around level 15

# (level, title)
TITLES = [
    (1, "Prompt Apprentice"), (4, "Shell Squire"), (7, "Code Knight"), (10, "Refactor Ranger"),
    (14, "Agent Commander"), (18, "Context Wizard"), (23, "Token Archmage"), (30, "Legend of Claude"),
]

# (level, id, name, what it does). game.js draws the hero and the arena from the unlocked ids.
UNLOCKS = [
    (1, "sword", "Wooden sword", "Every hero starts somewhere"),
    (2, "cry", "Battle cry", "The hero talks while fighting"),
    (3, "cape", "Cape", "Flutters while working"),
    (5, "blade", "Glowing blade", "The sword turns into light"),
    (6, "sound", "Battle sounds", "Synth sounds for hits and level-ups (toggle in the sheet)"),
    (7, "shield", "Shield", "Blocks counter attacks"),
    (9, "helmet", "Helmet", "Looks the part"),
    (11, "drone", "Dragon familiar", "A small golden dragon that breathes fire along with you"),
    (13, "crit", "Critical hits", "Big XP gains land as critical hits"),
    (15, "aura", "Aura", "Golden glow around the hero"),
    (18, "twin", "Twin blades", "Two blades, double the hits"),
    (21, "wings", "Wings", "The hero hovers above the floor"),
    (25, "lightning", "Lightning", "Finishing moves with lightning"),
    (30, "crown", "Crown", "Legend of Claude"),
]


def level_for(xp: int) -> int:
    """Level L needs 250 * (L-1)^2 XP: 250, 1000, 2250 … each level takes a bit longer."""
    lvl = 1
    while LEVEL_XP * lvl * lvl <= xp:
        lvl += 1
    return lvl


def xp_for(level: int) -> int:
    return LEVEL_XP * (level - 1) ** 2


def _streaks(days: set[str], today: str) -> tuple[int, int]:
    """(current, best) run of consecutive days with prompts; current counts if yesterday was active."""
    if not days:
        return 0, 0
    ds = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in days)
    best = run = 1
    for a, b in zip(ds, ds[1:]):
        run = run + 1 if b - a == timedelta(days=1) else 1
        best = max(best, run)
    t = datetime.strptime(today, "%Y-%m-%d").date()
    cur = run if t - ds[-1] <= timedelta(days=1) else 0
    return cur, best


def _counts(sessions: list[dict], output_tokens: int) -> dict:
    counts = {k: 0 for k in XP}
    for s in sessions:
        counts["prompt"] += s["prompts"]
        for ev, n in s["xp"].items():
            if ev in counts:  # unknown events (e.g. from a newer ledger) give no XP
                counts[ev] += n
    counts["kilotoken"] = output_tokens // 1000
    return counts


def _xp(counts: dict) -> int:
    return sum(XP[k][0] * n for k, n in counts.items())


def state(sessions: list[dict], today: str, started: datetime | None = None, archived: list[dict] = ()) -> dict:
    """sessions are the game views of the transcripts on disk (collect.new_game_view plus
    subagent, title, cwd), archived the ledger entries of deleted ones; both count only
    activity since the game start."""
    archived = list(archived)
    every = list(sessions) + archived
    tokens, t, models, active = Counter(), Counter(), set(), set()  # t: today's counters, active: days with prompts
    hours = [0] * 24
    longest = 0.0
    feats = []
    for s in every:
        tokens.update(s["tokens"])
        models.update(s["models"])
        days = s["days"]
        active.update(d for d, c in days.items() if c.get("prompts"))
        if today in days:
            t.update(days[today])
        for h, n in s["hours"].items():
            hours[h] += n
        if not s["subagent"] and s["start"] and s["end"]:
            longest = max(longest, (s["end"] - s["start"]).total_seconds() / 3600)
        for ts, ev in s["feats"]:
            if ev in XP:
                feats.append((ts, ev, s["title"] or (s["cwd"] or "?").rsplit("/", 1)[-1]))
    counts = _counts(every, tokens["output_tokens"])
    xp = _xp(counts)
    # the part of xp that only the ledger still knows
    live_out = tokens["output_tokens"] - sum(a["tokens"].get("output_tokens", 0) for a in archived)
    archived_xp = xp - _xp(_counts(sessions, live_out)) if archived else 0
    xp_today = (t.get("prompts", 0) * XP["prompt"][0] + t.get("output_tokens", 0) // 1000
                + sum(XP[k][0] * v for k, v in ((k[3:], v) for k, v in t.items() if k.startswith("xp_")) if k in XP))
    lvl = level_for(xp)
    cur, best = _streaks(active, today)
    cache_in = sum(tokens[k] for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    cache_hit = tokens["cache_read_input_tokens"] / cache_in if cache_in else 0

    ach = [
        ("first-blood", "First Blood", "Make your first commit", counts["commit"] >= 1),
        ("merge-master", "Merge Master", "Open 10 pull requests", counts["pr"] >= 10),
        ("test-paladin", "Test Paladin", "Run tests 100 times", counts["test"] >= 100),
        ("release-ranger", "Release Ranger", "Deploy 10 times", counts["deploy"] >= 10),
        ("bug-slayer", "Bug Slayer", "Slay 100 bugs", counts["bugfix"] >= 100),
        ("hive-mind", "Hive Mind", "Send 50 subagents", counts["agent"] >= 50),
        ("toolsmith", "Toolsmith", "10,000 tool calls", counts["tool"] + counts["edit"] >= 10000),
        ("token-tycoon", "Token Tycoon", "1M output tokens", counts["kilotoken"] >= 1000),
        ("model-whisperer", "Model Whisperer", "Work with 4 different models", len(models) >= 4),
        ("cache-king", "Cache King", "Cache hit rate above 90%", cache_hit > .9),
        ("night-owl", "Night Owl", "Prompt between 22:00 and 04:00", sum(hours[h] for h in (22, 23, 0, 1, 2, 3)) > 0),
        ("early-bird", "Early Bird", "Prompt before 07:00", sum(hours[h] for h in range(4, 7)) > 0),
        ("marathon", "Marathon", "A session of 3+ hours", longest >= 3),
        ("on-a-roll", "On a Roll", "5 active days in a row", best >= 5),
        ("unstoppable", "Unstoppable", "10 active days in a row", best >= 10),
    ]
    title = [t for lv, t in TITLES if lv <= lvl][-1]
    nxt = next(((lv, t) for lv, t in TITLES if lv > lvl), None)
    return {
        "xp": xp, "xpToday": xp_today, "level": lvl, "title": title,
        "levelXp": xp_for(lvl), "nextXp": xp_for(lvl + 1),
        "nextTitle": {"level": nxt[0], "title": nxt[1]} if nxt else None,
        "unlocks": [{"level": lv, "id": i, "name": n, "desc": d, "on": lv <= lvl} for lv, i, n, d in UNLOCKS],
        "achievements": [{"id": i, "name": n, "desc": d, "on": ok} for i, n, d, ok in ach],
        "sources": sorted(({"id": k, "label": XP[k][1], "count": n, "xp": XP[k][0] * n, "each": XP[k][0]}
                           for k, n in counts.items() if n), key=lambda r: -r["xp"]),
        "streak": cur, "bestStreak": best,
        "archivedSessions": len(archived), "archivedXp": archived_xp,
        "startedAt": started.isoformat(timespec="seconds") if started else None,
        "feats": [{"at": ts.isoformat(timespec="seconds"), "event": ev, "label": XP[ev][1], "xp": XP[ev][0], "where": w}
                  for ts, ev, w in heapq.nlargest(10, feats)],
    }
