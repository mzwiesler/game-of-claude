"""python3 -m unittest test_collect"""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import game
import ledger
from collect import Collector, feed, new_session, parse_file, status, tool_event

T0 = datetime(2026, 10, 21, 9, 0, 0).astimezone()


def rec(typ, sec, **kw):
    r = {"type": typ, "timestamp": (T0 + timedelta(seconds=sec)).isoformat(), "cwd": "/repo", "sessionId": "s1"}
    r.update(kw)
    return json.dumps(r) + "\n"


def assistant(sec, mid, blocks, stop="tool_use", out=10):
    usage = {"input_tokens": 1, "output_tokens": out, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 5}
    return rec("assistant", sec, message={"id": mid, "model": "claude-opus-5-5", "content": blocks, "stop_reason": stop, "usage": usage})


TRANSCRIPT = "".join([
    rec("user", 0, message={"role": "user", "content": "build a dashboard"}),
    assistant(1, "m1", [{"type": "thinking", "thinking": "…"}]),
    assistant(2, "m1", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),  # same message, usage once
    rec("user", 3, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True}]}),
    assistant(4, "m2", [{"type": "tool_use", "id": "t2", "name": "mcp__jira__search", "input": {}}]),
    rec("user", 5, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2"}]}),
    assistant(6, "m3", [{"type": "text", "text": "done"}], stop="end_turn", out=20),
    json.dumps({"type": "ai-title", "aiTitle": "Dashboard"}) + "\n",
])

FIELDS = ("prompts", "turns", "tokens", "tools", "errors", "title", "lastPrompt", "start", "end")


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "s1.jsonl"

    def test_full_parse(self):
        self.path.write_text(TRANSCRIPT)
        s = parse_file(self.path)
        self.assertEqual(s["prompts"], 1)
        self.assertEqual(s["turns"], 3)
        self.assertEqual(s["tokens"]["output_tokens"], 40)
        self.assertEqual(dict(s["tools"]), {"Bash": 1, "mcp:jira": 1})
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["title"], "Dashboard")
        self.assertEqual(status(s, T0 + timedelta(seconds=7)), "waiting")

    def test_incremental_equals_full(self):
        """Appending in arbitrary byte chunks, also mid-line, gives the same result as one parse."""
        data = TRANSCRIPT.encode()
        self.path.write_bytes(b"")
        s = new_session(self.path)
        for i in range(0, len(data), 37):
            with self.path.open("ab") as fh:
                fh.write(data[i:i + 37])
            feed(s, self.path, self.path.stat())
        full = parse_file(self.path)
        for f in FIELDS:
            self.assertEqual(s[f], full[f], f)

    def test_status(self):
        self.path.write_text(TRANSCRIPT.split(rec("user", 3, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True}]}))[0])
        s = parse_file(self.path)
        self.assertEqual(status(s, T0 + timedelta(seconds=5)), "working")
        self.assertEqual(status(s, T0 + timedelta(seconds=60)), "approval")

    def test_worktrees_group_by_repo_and_facets(self):
        wt = TRANSCRIPT.replace('"cwd": "/repo"', '"cwd": "/repo/.claude/worktrees/x"').replace(
            '"id": "m3", "model": "claude-opus-5-5"', '"id": "m3", "model": "claude-haiku-5-5"')
        self.path.write_text(TRANSCRIPT)
        (self.dir / "s2.jsonl").write_text(wt)
        snap = Collector(self.dir, ledger=None).snapshot()
        self.assertEqual([(p["path"], p["sessions"]) for p in snap["projects"]], [("/repo", 2)])
        f = {x["id"]: x for x in snap["facets"]}
        self.assertEqual((f["s2"]["repo"], f["s2"]["project"]), ("/repo", "/repo/.claude/worktrees/x"))
        self.assertNotIn("modelDays", f["s1"])  # one model: days says it all
        day = T0.strftime("%Y-%m-%d")
        self.assertEqual(f["s2"]["modelDays"][day]["claude-haiku-5-5"]["output_tokens"], 20)
        self.assertEqual(f["s2"]["models"]["claude-opus-5-5"]["turns"], 2)

    def test_rewritten_file_is_reparsed(self):
        c = Collector(self.dir, ledger=None)
        self.path.write_text(TRANSCRIPT)
        self.assertTrue(c.refresh())
        self.assertFalse(c.refresh())
        self.path.write_text(rec("user", 0, message={"role": "user", "content": "short"}))
        self.assertTrue(c.refresh())
        self.assertEqual(c.sessions()[0]["prompts"], 1)
        self.assertEqual(c.sessions()[0]["turns"], 0)
        self.path.unlink()
        self.assertTrue(c.refresh())
        self.assertEqual(c.sessions(), [])


class GameTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "s1.jsonl"

    def test_tool_events(self):
        bash = lambda c: tool_event("Bash", {"command": c})
        self.assertEqual(bash('git add . && git commit -m "x"'), "commit")
        self.assertEqual(bash("gh pr create --fill"), "pr")
        self.assertEqual(bash("cd infra && terraform apply -auto-approve"), "deploy")
        self.assertEqual(bash("kubectl --context lan-test-k8s apply -f x.yaml"), "deploy")
        self.assertEqual(bash("python3 -m pytest -q"), "test")
        self.assertEqual(bash("ls -la"), "tool")
        self.assertEqual(tool_event("Edit", {}), "edit")
        self.assertEqual(tool_event("mcp__jira__search", {}), "mcp")

    def test_levels(self):
        self.assertEqual(game.level_for(0), 1)
        self.assertEqual(game.level_for(game.LEVEL_XP - 1), 1)
        self.assertEqual(game.level_for(game.LEVEL_XP), 2)
        for lv in range(1, 40):
            self.assertEqual(game.level_for(game.xp_for(lv)), lv)

    def test_bug_slain_and_xp(self):
        self.path.write_text(TRANSCRIPT)
        s = parse_file(self.path)  # Bash failed, no retry: no bug slain yet
        self.assertEqual(s["g"]["xp"]["bugfix"], 0)
        retry = assistant(7, "m4", [{"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "git commit -m fix"}}]) + \
            rec("user", 8, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t3"}]})
        self.path.write_text(TRANSCRIPT + retry)
        s = parse_file(self.path)
        self.assertEqual(s["g"]["xp"]["bugfix"], 1)
        self.assertEqual(s["g"]["xp"]["commit"], 1)
        g = game.state([ledger.summary(s)], "2026-10-21")
        self.assertEqual(g["xp"], 5 + 1 + 3 + 25 + 8)  # prompt, tool, mcp, commit, bugfix
        self.assertTrue(next(a for a in g["achievements"] if a["id"] == "first-blood")["on"])


COMMIT = assistant(7, "m4", [{"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "git commit -m fix"}}]) + \
    rec("user", 8, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t3"}]})


class LedgerTest(unittest.TestCase):
    """XP of transcripts that Claude Code deleted stays in the ledger. Unless a test starts a
    new game, the game started an hour before the transcripts (T0)."""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.root, self.ledger = tmp / "projects", tmp / "data" / "ledger.json"
        self.main = self.root / "-repo" / "s1.jsonl"
        self.sub = self.root / "-repo" / "s1" / "subagents" / "agent-a1.jsonl"  # same sessionId dir, own key
        self.sub.parent.mkdir(parents=True)
        self.main.write_text(TRANSCRIPT + COMMIT)
        self.sub.write_text(TRANSCRIPT)
        ledger.save(self.ledger, T0 - timedelta(hours=1), {})

    def game(self, c):
        return c.snapshot()["game"]

    def test_deleted_transcript_keeps_xp(self):
        c = Collector(self.root, self.ledger)
        before = self.game(c)
        self.assertEqual(before["archivedSessions"], 0)
        self.main.unlink()
        after = self.game(c)  # deleted before any save: summarized on deletion
        for k in ("xp", "level", "streak", "bestStreak"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual([a["on"] for a in after["achievements"]], [a["on"] for a in before["achievements"]])
        self.assertEqual(after["archivedSessions"], 1)
        self.assertEqual(after["archivedXp"], 5 + 1 + 3 + 25 + 8)
        self.assertEqual(c.snapshot()["kpi"]["sessions"], 0)  # dashboard stats stay on-disk only

    def test_round_trip(self):
        c = Collector(self.root, self.ledger)
        before = self.game(c)
        self.assertTrue(c.save(force=True))
        self.assertFalse(c.save(force=True))  # nothing changed, no write
        self.assertEqual(set(json.loads(self.ledger.read_text())["sessions"]), {str(self.main), str(self.sub)})
        self.main.unlink()
        self.sub.unlink()
        after = self.game(Collector(self.root, self.ledger))
        for k in ("xp", "level", "xpToday", "streak", "bestStreak", "sources", "feats"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual(after["archivedSessions"], 2)
        self.assertEqual(after["archivedXp"], before["xp"])

    def test_live_file_wins(self):
        c = Collector(self.root, self.ledger)
        c.refresh()
        c.save(force=True)
        self.main.write_text(TRANSCRIPT)  # ledger copy is outdated, the file on disk counts
        c2 = Collector(self.root, self.ledger)
        g = self.game(c2)
        self.assertEqual(g["archivedSessions"], 0)
        self.assertEqual(g["archivedXp"], 0)
        self.assertEqual(g["xp"], 2 * (5 + 1 + 3))

    def test_save_is_throttled(self):
        c = Collector(self.root, self.ledger)
        c.refresh()
        self.assertTrue(c.save())
        with self.main.open("a") as fh:
            fh.write(rec("user", 9, message={"role": "user", "content": "more"}))
        c.refresh()
        self.assertFalse(c.save())  # within LEDGER_EVERY
        self.assertTrue(c.save(force=True))

    def test_corrupt_ledger(self):
        self.ledger.write_text('{"version": 1, "sessions": {"x": ')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            c = Collector(self.root, self.ledger)
        self.assertIn("corrupt", err.getvalue())
        self.assertEqual(c.ledger, {})
        self.assertTrue((self.ledger.parent / "ledger.json.bak").exists())
        self.assertFalse(self.ledger.exists())
        self.assertEqual(self.game(c)["xp"], 0)  # a new game
        self.assertTrue(c.save(force=True))
        self.assertEqual(ledger.load(self.ledger)[0], c.start)
        for doc in ("[1, 2]", '{"sessions": {}}', '{"startedAt": "yesterday", "sessions": {}}'):  # wrong shape, no start
            self.ledger.write_text(doc)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ledger.load(self.ledger), (None, {}), doc)
            self.assertFalse(self.ledger.exists())

    def test_malformed_entry_skipped(self):
        good = ledger.encode(ledger.summary(parse_file(self.main)))
        self.ledger.write_text(json.dumps({"version": 1, "startedAt": T0.isoformat(),
                                           "sessions": {str(self.root / "gone.jsonl"): good, "bad": {"xp": 1}}}))
        with contextlib.redirect_stderr(io.StringIO()):
            start, entries = ledger.load(self.ledger)
        self.assertEqual(start, T0)
        self.assertEqual(list(entries), [str(self.root / "gone.jsonl")])

    def test_other_root_not_counted(self):
        c = Collector(self.root, self.ledger)
        c.refresh()
        c.save(force=True)
        other = Collector(self.root.parent / "elsewhere", self.ledger)
        self.assertEqual(self.game(other)["archivedSessions"], 0)


def now_rec(**kw):
    """A record a few seconds from now, i.e. after a game that starts now."""
    return rec("user", (datetime.now().astimezone() - T0).total_seconds() + 5,
               message={"role": "user", "content": "go on"}, **kw)


class NewGameTest(unittest.TestCase):
    """The hero starts at level 1: only activity since the game start counts."""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.root, self.ledger = tmp / "projects", tmp / "ledger.json"
        self.path = self.root / "-repo" / "s1.jsonl"
        self.path.parent.mkdir(parents=True)
        self.path.write_text(TRANSCRIPT + COMMIT)  # history from before the start

    def test_fresh_ledger_starts_at_level_1(self):
        c = Collector(self.root, self.ledger)
        g = c.snapshot()["game"]
        self.assertEqual((g["xp"], g["level"], g["xpToday"], g["feats"], g["streak"]), (0, 1, 0, [], 0))
        self.assertFalse(any(a["on"] for a in g["achievements"]))
        self.assertEqual(g["startedAt"], c.start.isoformat(timespec="seconds"))
        self.assertEqual(c.snapshot()["kpi"]["prompts"], 1)  # the dashboard still shows the history
        self.assertTrue(c.save(force=True))
        self.assertEqual(ledger.load(self.ledger)[0], c.start)  # the start persists

    def test_activity_after_start_counts_and_survives_deletion(self):
        c = Collector(self.root, self.ledger)
        c.refresh()
        with self.path.open("a") as fh:
            fh.write(now_rec())
        g = c.snapshot()["game"]
        self.assertEqual((g["xp"], g["xpToday"], g["streak"]), (5, 5, 1))
        c.save(force=True)
        self.path.unlink()
        g = Collector(self.root, self.ledger).snapshot()["game"]
        self.assertEqual((g["xp"], g["archivedSessions"], g["archivedXp"]), (5, 1, 5))

    def test_new_game_resets(self):
        ledger.save(self.ledger, T0 - timedelta(hours=1), {})
        c = Collector(self.root, self.ledger)
        self.assertEqual(c.snapshot()["game"]["xp"], 5 + 1 + 3 + 25 + 8)
        c.save(force=True)
        self.path.parent.joinpath("old.jsonl").write_text(TRANSCRIPT)
        c.refresh()
        self.path.parent.joinpath("old.jsonl").unlink()
        c.refresh()  # an archived session of the old game
        self.assertEqual(c.snapshot()["game"]["archivedSessions"], 1)
        c.new_game()
        g = c.snapshot()["game"]
        self.assertEqual((g["xp"], g["level"], g["archivedSessions"]), (0, 1, 0))
        self.assertEqual(len(list(self.ledger.parent.glob("ledger.json.*.bak"))), 1)
        self.assertTrue(c.save(force=True))
        start, entries = ledger.load(self.ledger)
        self.assertEqual((start, entries), (c.start, {}))


if __name__ == "__main__":
    unittest.main()
