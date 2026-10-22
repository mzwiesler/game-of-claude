"""python3 -m unittest test_insights"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import insights

NOW = datetime.now().astimezone()


def rec(typ, sec, cwd="/repo", **kw):
    r = {"type": typ, "timestamp": (NOW - timedelta(hours=1) + timedelta(seconds=sec)).isoformat(), "cwd": cwd}
    r.update(kw)
    return r


def prompt(sec, text, **kw):
    return rec("user", sec, message={"role": "user", "content": text}, **kw)


def bash(sec, mid, cmd, tid, unsandboxed=False, **kw):
    inp = {"command": cmd, **({"dangerouslyDisableSandbox": True} if unsandboxed else {})}
    usage = {"input_tokens": 1, "output_tokens": 10, "cache_read_input_tokens": 1000}
    return rec("assistant", sec, message={"id": mid, "model": "claude-opus-5-5", "usage": usage,
                                          "content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": inp}]}, **kw)


def error(sec, tid, text, **kw):
    return rec("user", sec, message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "is_error": True, "content": text}]}, **kw)


class InsightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, records):
        p = self.root / "-repo" / f"{name}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r) + "\n" for r in records))

    def report(self, settings=None):
        sessions = insights.scan(self.root, NOW - timedelta(days=7))
        return insights.analyze(sessions, settings or {}, 7, NOW), {f["id"]: f for f in insights.analyze(sessions, settings or {}, 7, NOW)["findings"]}

    def test_env_prefix_unless_already_in_settings(self):
        self.write("a", [prompt(0, "build it")] + [bash(i + 1, f"m{i}", f"GH_HOST=x gh pr view {i}", f"t{i}") for i in range(9)])
        _, f = self.report()
        self.assertIn("GH_HOST 9×", f["env-prefix"]["evidence"])
        _, f = self.report({"env": {"GH_HOST": "x"}})
        self.assertNotIn("env-prefix", f)

    def test_error_classes(self):
        recs = [prompt(0, "go")]
        for i in range(5):
            recs += [bash(10 * i + 1, f"m{i}", "databricks api get $x", f"t{i}"),
                     error(10 * i + 2, f"t{i}", "This session is isolated in the worktree /repo/.claude/worktrees/x, but …")]
        recs += [bash(60, "h1", "git commit -m x", "h1"), error(61, "h1", "PreToolUse:Bash hook error: failed:\n\nterraform validate: skipped prod/"),
                 bash(62, "h2", "git commit -m x", "h2"), error(63, "h2", "PreToolUse:Bash hook error: failed:\n\nterraform validate: skipped prod/")]
        self.write("a", recs)
        _, f = self.report()
        self.assertIn("5 refusals", f["worktree-guard"]["evidence"])
        self.assertIn("terraform validate: skipped prod/ 2×", f["hook"]["evidence"])

    def test_sandbox_bypass_groups_by_command(self):
        recs = [prompt(0, "please run this outside the sandbox")]
        recs += [bash(i + 1, f"m{i}", f"B=$(ls -d /x/*/); az account show {i}", f"t{i}", unsandboxed=True) for i in range(15)]
        self.write("a", recs)
        _, f = self.report()
        self.assertIn("az account 15×", f["sandbox"]["evidence"])
        self.assertIn("asked 1×", f["sandbox"]["evidence"])

    def test_recurring_request_needs_three_sessions(self):
        for i, n in enumerate(["a", "b", "c"]):
            self.write(n, [prompt(i * 1000, "check latest tf run on qual"), prompt(i * 1000 + 5, "and the terraform plan for prod")])
        _, f = self.report()
        self.assertIn("6 prompts in 3 sessions", f["request:Check / debug a Terraform run"]["evidence"])
        self.assertIn("phrase:check latest tf run", f)

    def test_parallel_duplicates_and_slash_commands_and_subagents(self):
        task = "deploy same infrastructure we currently have to qual"
        self.write("a", [prompt(0, task), prompt(5, "<command-name>/mcp</command-name>")])
        self.write("b", [prompt(60, task)])
        sub = self.root / "-repo" / "a" / "subagents" / "agent-1.jsonl"
        sub.parent.mkdir(parents=True)
        sub.write_text(json.dumps(prompt(70, "subagent prompt", isSidechain=True)) + "\n")
        rep, f = self.report()
        self.assertIn("deploy same", f["duplicates"]["evidence"])
        self.assertEqual(rep["stats"]["sessions"], 2)  # the subagent file is not a session
        self.assertEqual(rep["stats"]["prompts"], 2)  # slash commands and sidechain prompts are not prompts
        self.assertEqual(rep["slashCommands"], [("mcp", 1)])

    def test_old_records_are_ignored(self):
        old = prompt(0, "check latest tf run")
        old["timestamp"] = (NOW - timedelta(days=30)).isoformat()
        self.write("a", [old])
        rep, _ = self.report()
        self.assertEqual(rep["stats"]["sessions"], 0)

    def test_save_and_latest(self):
        self.write("a", [prompt(0, "hello there")])
        rep, _ = self.report()
        out = self.root / "out"
        path = insights.save(rep, out)
        self.assertTrue(path.name.startswith(NOW.strftime("%Y-%m-%d")))
        self.assertEqual(insights.latest(out)["generatedAt"], rep["generatedAt"])

    def test_cmd_key(self):
        self.assertEqual(insights._cmd_key("cd /x && GH_HOST=h gh pr create -t x"), "gh pr")
        self.assertEqual(insights._cmd_key("S=/tmp/a; set -a; for f in *; do echo; done"), "loop")
        self.assertEqual(insights._cmd_key("B=$(ls -d ~/x/*/) && podman ps -a"), "podman ps")


if __name__ == "__main__":
    unittest.main()
