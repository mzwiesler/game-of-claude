"""XP ledger: the game start and the game view of every transcript ever seen, so XP survives
Claude Code deleting old transcripts (cleanupPeriodDays, default 30).

One compact JSON file, keyed by transcript path (sessionId is not unique: a session's subagent
files live in <sessionId>/subagents/agent-*.jsonl next to it). Counters, start/end and feats
only cover records at or after "startedAt" (collect.new_game_view):

    {"version": 1, "startedAt": "2026-10-21T14:00:00+02:00", "updated": "…",
     "sessions": {"/…/projects/-repo/<id>.jsonl": {
        "id": "<id>", "subagent": false, "title": "…", "cwd": "/repo",
        "start": "2026-10-21T14:05:00+02:00", "end": "…", "prompts": 3,
        "tokens": {"output_tokens": 40, …}, "xp": {"tool": 2, …}, "hours": {"14": 3},
        "days": {"2026-10-21": {"prompts": 3, "output_tokens": 40, "xp_tool": 2}},
        "models": ["claude-opus-5-5"], "feats": [["2026-10-21T14:05:08+02:00", "commit"]]}}}

In memory an entry looks like a session's game view (datetimes, Counters), so game.state
counts it like a live one.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

VERSION = 1
PATH = Path(os.environ.get("CLAUDE_TELEMETRY_LEDGER") or
            Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "claude-telemetry" / "ledger.json")


def _nz(c: dict) -> dict:
    return {k: v for k, v in c.items() if v}


def summary(s: dict) -> dict:
    """Ledger entry of a parsed collect.py session: its meta data and a copy of its game view."""
    g = s["g"]
    return {
        "sessionId": s["sessionId"], "subagent": s["subagent"], "title": s["title"], "cwd": s["cwd"],
        "start": g["start"], "end": g["end"], "prompts": g["prompts"],
        "tokens": Counter(_nz(g["tokens"])), "xp": Counter(_nz(g["xp"])), "hours": _nz(g["hours"]),
        "days": {d: dict(c) for d, c in g["days"].items() if c}, "models": set(g["models"]), "feats": list(g["feats"]),
    }


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat(timespec="seconds") if ts else None


def _dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def encode(e: dict) -> dict:
    return {
        "id": e["sessionId"], "subagent": e["subagent"], "title": e["title"], "cwd": e["cwd"],
        "start": _iso(e["start"]), "end": _iso(e["end"]), "prompts": e["prompts"],
        "tokens": dict(e["tokens"]), "xp": dict(e["xp"]), "hours": {str(h): n for h, n in e["hours"].items()},
        "days": e["days"], "models": sorted(e["models"]), "feats": [[_iso(ts), ev] for ts, ev in e["feats"]],
    }


def decode(d: dict) -> dict:
    """Raises on malformed entries (KeyError, TypeError, ValueError, AttributeError)."""
    return {
        "sessionId": str(d["id"]), "subagent": bool(d["subagent"]), "title": d.get("title"), "cwd": d.get("cwd"),
        "start": _dt(d.get("start")), "end": _dt(d.get("end")), "prompts": int(d.get("prompts", 0)),
        "tokens": Counter({str(k): int(v) for k, v in d.get("tokens", {}).items()}),
        "xp": Counter({str(k): int(v) for k, v in d.get("xp", {}).items()}),
        "hours": {int(h): int(n) for h, n in d.get("hours", {}).items() if 0 <= int(h) < 24},
        "days": {str(day): {str(k): int(v) for k, v in c.items()} for day, c in d.get("days", {}).items()},
        "models": {str(m) for m in d.get("models", [])},
        "feats": [(datetime.fromisoformat(ts), str(ev)) for ts, ev in d.get("feats", [])],
    }


def _warn(msg: str) -> None:
    print(f"ledger: {msg}", file=sys.stderr, flush=True)


def _backup(path: Path, bak: Path) -> None:
    try:
        os.replace(path, bak)
    except OSError:
        pass


def load(path: Path) -> tuple[datetime | None, dict[str, dict]]:
    """(game start, entries). Missing file: (None, {}), i.e. a new game. Unreadable or corrupt
    file: warning, moved to <name>.bak (if it is not a valid ledger at all), new game. Single
    bad entries are skipped."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, {}
    except OSError as e:
        _warn(f"cannot read {path}: {e}, starting a new game")
        return None, {}
    bak = path.with_name(path.name + ".bak")
    try:
        doc = json.loads(raw)
        items = doc["sessions"].items()
        start = datetime.fromisoformat(doc["startedAt"]).astimezone() if "startedAt" in doc else None
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        _warn(f"{path} is corrupt ({e!r}), kept as {bak.name}, starting a new game")
        _backup(path, bak)
        return None, {}
    if start is None:  # written before game starts existed
        _warn(f"{path} has no game start, kept as {bak.name}, starting a new game")
        _backup(path, bak)
        return None, {}
    out, bad = {}, 0
    for k, d in items:
        try:
            out[str(k)] = decode(d)
        except (KeyError, TypeError, ValueError, AttributeError):
            bad += 1
    if bad:
        _warn(f"skipped {bad} malformed entries in {path}")
    return start, out


def save(path: Path, start: datetime, entries: dict[str, dict]) -> None:
    """Atomic write: tmp file next to the ledger, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"version": VERSION, "startedAt": start.isoformat(),
                       "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
                       "sessions": {k: encode(e) for k, e in entries.items()}}, separators=(",", ":"))
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
