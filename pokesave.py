"""Pokémon theme save (poke.js) on disk, next to the XP ledger, so it is shared by every browser
and survives clearing site data. The browser keeps a copy in localStorage as a cache.

    {"v": 1, "partner": 1729500000123, "updated": "…",
     "box": [{"u": 1729500000123, "id": 25, "exp": 5832, "at": 1729500000123}],
     "seen": {"25": 1}, "w": 87, "l": 9}

Writes merge with what is on disk, so two dashboard windows can't drop each other's catches:
every Pokémon (by uid "u") is kept, the copy with more EXP wins (it may have evolved), the
Pokédex is the union, win/loss counts take the maximum, the partner comes from the newest write.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

import ledger

NAME = "pokemon.json"
MAX_BYTES = 512 * 1024
_lock = threading.Lock()


def path_for(ledger_path: Path | None) -> Path:
    return (ledger_path or ledger.PATH).parent / NAME


def blank() -> dict:
    return {"v": 1, "partner": None, "box": [], "seen": {}, "w": 0, "l": 0}


def _int(v, lo: int = 0, hi: int = 2 ** 53) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def clean(doc) -> dict:
    """Keep only well-formed fields: Pokémon #1–150, non-negative integers."""
    out = blank()
    if not isinstance(doc, dict):
        return out
    seen_u = set()
    for m in doc.get("box") if isinstance(doc.get("box"), list) else []:
        if not isinstance(m, dict):
            continue
        u, pid, exp = _int(m.get("u"), 1), _int(m.get("id"), 1, 150), _int(m.get("exp"), 0, 10 ** 7)
        if u is None or pid is None or exp is None or u in seen_u:
            continue
        seen_u.add(u)
        out["box"].append({"u": u, "id": pid, "exp": exp, "at": _int(m.get("at")) or 0})
    seen = doc.get("seen") if isinstance(doc.get("seen"), dict) else {}
    out["seen"] = {k: 1 for k in seen if k.isdigit() and 1 <= int(k) <= 150}
    for b in out["box"]:
        out["seen"][str(b["id"])] = 1
    out["w"], out["l"] = _int(doc.get("w")) or 0, _int(doc.get("l")) or 0
    p = _int(doc.get("partner"), 1)
    out["partner"] = p if p in seen_u else None
    return out


def merge(old: dict, new: dict) -> dict:
    """Both already cleaned. See the module docstring for the rules."""
    box = {m["u"]: dict(m) for m in old["box"]}
    for m in new["box"]:
        if m["u"] not in box or m["exp"] > box[m["u"]]["exp"]:
            box[m["u"]] = dict(m)
    out = blank()
    out["box"] = sorted(box.values(), key=lambda m: (m["at"], m["u"]))
    out["seen"] = {**old["seen"], **new["seen"]}
    out["w"], out["l"] = max(old["w"], new["w"]), max(old["l"], new["l"])
    out["partner"] = new["partner"] if new["partner"] in box else old["partner"] if old["partner"] in box else None
    return out


def load(path: Path) -> dict:
    try:
        return clean(json.loads(path.read_bytes()))
    except FileNotFoundError:
        return blank()
    except (OSError, ValueError) as e:
        print(f"pokesave: cannot read {path} ({e}), starting empty", file=sys.stderr, flush=True)
        return blank()


def update(path: Path, incoming) -> dict:
    """Merge an incoming save into the file (atomic write) and return the merged save."""
    with _lock:
        doc = merge(load(path), clean(incoming))
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({**doc, "updated": datetime.now().astimezone().isoformat(timespec="seconds")}, separators=(",", ":"))
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return doc
