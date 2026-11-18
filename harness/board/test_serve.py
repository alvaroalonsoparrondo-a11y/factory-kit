"""Tests of the local board server's helpers. Human-owned.

Run: python3 -m unittest discover -s harness/board -v
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import serve as s


class Helpers(unittest.TestCase):
    def test_repo_from_url(self):
        self.assertEqual(s.repo_from_url("https://github.com/o/r.git\n"), "o/r")
        self.assertEqual(s.repo_from_url("git@github.com:o/r.git"), "o/r")
        self.assertEqual(s.repo_from_url("https://github.com/o/r"), "o/r")
        self.assertIsNone(s.repo_from_url("https://example.com/o/r.git"))

    def test_ticket_markdown(self):
        t = {"ref": "1.2", "title": "Redirect", "risk": "high", "covers": ["R5"], "after": ["1"],
             "description": "Adds GET.", "verify": "Tests pass.", "notes": ["A note."]}
        row = {"stage": "Planned", "status": "needs you", "needs_you": "Start the lap", "blocked": None}
        md = s.ticket_markdown(t, row)
        self.assertTrue(md.startswith("# 1.2: Redirect\n"))
        self.assertIn("Stage: Planned · Status: needs you · Risk: high · Covers: R5 · After: #1", md)
        self.assertIn("**Needs you:** Start the lap", md)
        self.assertIn("## Verify\n\nTests pass.", md)
        self.assertIn("- A note.", md)

    def test_github_answers_are_cached(self):
        calls = []

        class Fake:
            repo = "o/r"

            def get(self, path, key=None):
                calls.append(path)
                return [len(calls)]

        gh = s.CachedGitHub(Fake(), seconds=60)
        self.assertEqual(gh.get("/pulls"), [1])
        self.assertEqual(gh.get("/pulls"), [1])
        self.assertEqual(gh.get("/pulls", key="x"), [2])
        gh.seconds = -1
        self.assertEqual(gh.get("/pulls"), [3])

    def test_without_a_token_there_are_no_pull_requests(self):
        self.assertEqual(s.NoGitHub("o/r").get("/pulls?state=all"), [])

    def test_ticket_markdown_lists_the_stops(self):
        t = {"ref": "1.1", "title": "Skeleton"}
        row = {"stage": "Building", "status": "needs you", "needs_you": "Approve the plan (approval, waiting 3 min)",
               "blocked": None, "human_wait": {"stops": 2, "seconds": 900},
               "reviews": {"bmad": 2, "fix_rounds": 0, "human": 0, "findings": {"found": 5, "patched": 3, "deferred": 1}},
               "stops": [{"at": "2026-11-18T10:00:00+00:00", "kind": "permission", "text": "Subagents?", "seconds": 720, "open": False},
                         {"at": "2026-11-18T11:00:00+00:00", "kind": "approval", "text": "Approve the plan", "seconds": 180, "open": True}]}
        md = s.ticket_markdown(t, row)
        self.assertIn("not evidence about the work", md)
        self.assertIn("| 2026-11-18T10:00:00+00:00 | permission | Subagents? | 12 min |", md)
        self.assertIn("| Approve the plan | 3 min so far |", md)
        self.assertIn("2 stops, 15 min in total.", md)
        self.assertIn("**Reviews:** 2 BMAD passes, 5 found, 3 patched, 1 deferred.", md)


class LocalFiles(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_read_signals(self):
        (self.root / ".lap").mkdir()
        (self.root / ".lap" / "1.1.jsonl").write_text(
            '{"at": "2026-11-18T10:00:00+00:00", "state": "working"}\nnot json\n\n', encoding="utf-8")
        (self.root / ".lap" / "1.1-pr.md").write_text("# PR", encoding="utf-8")
        problems = []
        self.assertEqual(s.read_signals(self.root, problems), {"1.1": [{"at": "2026-11-18T10:00:00+00:00", "state": "working"}]})
        self.assertEqual(problems, ["`.lap/1.1.jsonl` line 2 cannot be read."])

    def test_no_lap_folder(self):
        self.assertEqual(s.read_signals(self.root, []), {})

    def test_newest_change_skips_git_node_modules_and_lap(self):
        old, new = 1_700_000_000, 1_700_000_500
        for rel, when in (("backend/target/x.class", new), ("src/a.txt", old),
                          (".git/index", new + 99), ("node_modules/p/i.js", new + 99), (".lap/1.1.jsonl", new + 99)):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
            os.utime(p, (when, when))
        for d in ("backend/target", "backend", "src", ".git", "node_modules/p", "node_modules", ".lap"):
            os.utime(self.root / d, (old, old))
        self.assertEqual(s.newest_change(self.root), new)

    def test_newest_change_leaves_out_a_nested_worktree(self):
        old, new = 1_700_000_000, 1_700_000_500
        lap = self.root / ".claude" / "worktrees" / "lap"
        lap.mkdir(parents=True)
        (lap / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
        (lap / "busy.txt").write_text("x", encoding="utf-8")
        os.utime(lap / "busy.txt", (new, new))
        (self.root / "a.txt").write_text("x", encoding="utf-8")
        for p in (self.root / "a.txt", lap / ".git", lap, lap.parent, lap.parent.parent):
            os.utime(p, (old, old))
        self.assertEqual(s.newest_change(self.root), old)
        self.assertEqual(s.newest_change(lap), new)

    def test_signals_from_several_working_trees_are_merged(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        for folder, line in ((self.root, '{"at": "t1", "state": "working"}'), (other, '{"at": "t2", "state": "working"}')):
            (folder / ".lap").mkdir()
            (folder / ".lap" / "1.3.jsonl").write_text(line + "\n", encoding="utf-8")
        out = s.read_signals(self.root, [])
        s.read_signals(other, [], out)
        self.assertEqual([e["at"] for e in out["1.3"]], ["t1", "t2"])


class Worktrees(unittest.TestCase):
    def test_story_branches_in_worktrees_are_found(self):
        with tempfile.TemporaryDirectory() as main, tempfile.TemporaryDirectory() as lap:
            porcelain = "\n".join([
                f"worktree {main}", "HEAD aaa", "branch refs/heads/main", "",
                f"worktree {lap}", "HEAD bbb", "branch refs/heads/story/1.3", "",
                f"worktree {lap}-gone", "HEAD ccc", "branch refs/heads/story/1.6",
                "prunable gitdir file points to non-existent location", "",
                f"worktree {main}-detached", "HEAD ddd", "detached", ""])
            self.assertEqual(s.parse_worktrees(porcelain), {"story/1.3": lap})

    def test_a_lap_in_another_worktree_is_read_from_its_working_tree(self):
        with tempfile.TemporaryDirectory() as main, tempfile.TemporaryDirectory() as lap:
            (Path(lap) / "plan.md").write_text("live", encoding="utf-8")
            src = s.Source(main, "o/r", s.NoGitHub("o/r"), "")
            listing = "\n".join([f"worktree {main}", "branch refs/heads/main", "",
                                 f"worktree {lap}", "branch refs/heads/story/1.3", ""])

            def git(*args):
                if args[:2] == ("worktree", "list"):
                    return listing
                if args[:2] == ("rev-parse", "--abbrev-ref"):
                    return "main\n"
                raise RuntimeError("not faked")

            src._git = git
            self.assertEqual(src.live_trees(), {"story/1.3": lap, "main": main})
            self.assertEqual(src._read("story/1.3", "plan.md"), "live")
            # Not checked out anywhere: read from origin, which this fake refuses.
            self.assertIsNone(src._read("story/1.6", "plan.md"))


if __name__ == "__main__":
    unittest.main()
