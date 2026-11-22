"""Tests of the lap's round budget. Human-owned.

Run: python -m unittest discover -s harness/board -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import board
import lap_round as lr


class RoundTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def events(self):
        return lr.read(self.root, "1.2")

    def take(self, source, finding):
        return lr.take(self.root, "1.2", source, finding)[0]

    def test_the_budget_is_shared_by_every_source(self):
        self.assertEqual(lr.BUDGET, 3)
        self.assertEqual([self.take(s, f"f {s}") for s in ("review", "gates", "ci")], [0, 0, 0])
        self.assertEqual(self.take("runtime", "f runtime"), lr.SPENT)
        s = lr.summary(self.events())
        self.assertEqual((s["used"], s["left"]), (3, 0))
        self.assertEqual(lr.text_of(s), "3 of 3 (review 1, gates 1, ci 1)")

    def test_a_spent_budget_stops_the_lap_on_the_board(self):
        for n in range(3):
            self.take("gates", f"finding {n}")
        code, message = lr.take(self.root, "1.2", "gates", "finding 3")
        self.assertEqual(code, lr.SPENT)
        self.assertIn("finding 0", message)  # every finding so far, for the human
        last = self.events()[-1]
        self.assertEqual((last["state"], last["kind"]), ("waiting", "limit"))
        stops = board._stops(self.events(), now=2e9)
        self.assertTrue(stops[-1]["open"])

    def test_the_same_finding_again_stops_instead_of_spending(self):
        self.assertEqual(self.take("gates", "LoginIT fails: 401"), 0)
        self.assertEqual(self.take("gates", "  loginit FAILS:   401 "), lr.REPEATED)
        self.assertEqual(lr.summary(self.events())["used"], 1)  # the refusal took no round
        self.assertEqual(self.events()[-1]["kind"], "decision")
        self.assertEqual(self.take("review", "LoginIT fails: 401"), 0)  # another source is another finding

    def test_a_grant_adds_rounds_and_allows_one_more_try_of_the_same_finding(self):
        self.take("gates", "x")
        self.assertEqual(self.take("gates", "x"), lr.REPEATED)
        lr.grant(self.root, "1.2", 1, "worth one more try")
        self.assertEqual(self.events()[-1]["state"], "working")  # the stop is answered
        self.assertEqual(self.take("gates", "x"), 0)
        self.assertEqual(lr.summary(self.events())["budget"], 4)

    def test_bad_input(self):
        for args in (("1.2", "infra", "x"), ("1.2", "gates", " "), ("../x", "gates", "x")):
            with self.assertRaises(ValueError):
                lr.take(self.root, *args)
        with self.assertRaises(ValueError):
            lr.grant(self.root, "1.2", 0, "why")

    def test_rounds_and_signals_share_one_file_and_the_board_reads_both(self):
        self.take("review", "bad plan")
        subprocess.run([sys.executable, str(Path(lr.__file__).with_name("lap_signal.py")), "1.2", "working"],
                       cwd=self.root, capture_output=True)
        lines = (Path(self.root) / ".lap" / "1.2.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(lines[0])["state"], "round")
        events = self.events()
        self.assertEqual(lr.summary(events)["used"], 1)
        self.assertEqual(board._stops(events, now=2e9), [])  # a round is not a stop

    def test_cli(self):
        subprocess.run(["git", "init", "-q", self.root], check=True)
        script = str(Path(lr.__file__))
        run = lambda *a: subprocess.run([sys.executable, script, "1.2", *a], cwd=self.root, capture_output=True, text=True)
        done = run("take", "gates", "red")
        self.assertEqual(done.returncode, 0)
        self.assertIn("Round 1 of 3 (gates)", done.stdout)
        self.assertIn("1 of 3 (gates 1)", run("status").stdout)
        self.assertEqual(run("take", "gates", "red").returncode, lr.REPEATED)


class ConfigTests(unittest.TestCase):
    def test_every_source_is_described(self):
        config = json.loads((Path(lr.__file__).resolve().parent.parent / "rounds.json").read_text())
        self.assertEqual(set(config["sources"]), {"review", "gates", "runtime", "ci", "main-moved"})
        self.assertTrue(all(config["sources"].values()))


if __name__ == "__main__":
    unittest.main()
