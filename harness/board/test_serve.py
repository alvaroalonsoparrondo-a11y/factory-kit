"""Tests of the local board server's helpers. Human-owned.

Run: python3 -m unittest discover -s harness/board -v
"""
import unittest

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


if __name__ == "__main__":
    unittest.main()
