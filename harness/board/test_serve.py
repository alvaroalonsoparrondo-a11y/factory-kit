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


if __name__ == "__main__":
    unittest.main()
