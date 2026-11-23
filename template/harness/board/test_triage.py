"""Tests of triage.py on a scratch Git repository. Human-owned.

Run: python -m unittest discover -s harness/board -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import triage as tr

TICKETS = "_bmad-output/init/tickets/epic-links/tickets"
EPIC_FILE = "_bmad-output/init/tickets/epic-links/epic-links.md"
TOML = """
[[entry]]
id = 1
title = "First"
after = []
touches = ["backend/link/**"]

[[entry]]
id = 2
title = "Second"
description = "{desc}"
after = [1]
risk = "{risk}"
touches = ["backend/link/**", "e2e/tests/1-2-*.spec.ts"]
"""
READY = {"ref": "2", "state": "ready-to-implement", "summary": "Clear and bounded.", "rationale": ["link/ has it"],
         "questions": [], "next_step": "Run the lap."}


class Triage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.write(f"{TICKETS}/tickets.toml", TOML.format(desc="Adds custom slugs.", risk="medium"))
        self.write(EPIC_FILE, "# Links\n")
        self.write("backend/link/Link.java", "class Link {}\n")
        self.write("frontend/app.ts", "x\n")
        self.commit("start")
        tr._cache.clear()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def load(self):
        return tr._load(str(self.root), "main", "2")

    def record(self, decision=READY):
        ticket, plans = self.load()
        rec = tr.build_record(dict(decision), str(self.root), "main", ticket, plans, now="2026-11-23T10:00:00+01:00")
        tr.write_record(self.root, rec)
        self.commit("triage 2")
        return rec

    def fresh(self):
        ticket, plans = self.load()
        return tr.freshness(str(self.root), "main", tr.read_record(str(self.root), "main", "2"), ticket, plans)

    # ---- the decision

    def test_parse_takes_the_last_object_with_a_state(self):
        text = 'log line {"x": 1}\n{"state": "wait", "summary": "a"}\nmore\n{"state": "needs-info", "summary": "b"}'
        self.assertEqual(tr.parse_decision(text)["state"], "needs-info")
        self.assertIsNone(tr.parse_decision("no json here"))

    def test_validate_refuses_what_cannot_be_recorded(self):
        ticket, _ = self.load()
        for bad in ({"state": "maybe", "summary": "x"}, {"state": "needs-info", "summary": "x", "questions": []},
                    {"state": "ready-to-implement", "summary": "x", "questions": ["which?"]},
                    {"state": "wait", "summary": ""}, {"ref": "9", "state": "wait", "summary": "x"}):
            with self.assertRaises(ValueError, msg=bad):
                tr.validate(bad, ticket)

    def test_validate_normalises_the_state_names(self):
        ticket, _ = self.load()
        self.assertEqual(tr.validate({"state": "Ready to implement", "summary": "x"}, ticket)["state"],
                         "ready-to-implement")
        self.assertEqual(tr.validate({"state": "Wait to implement", "summary": "x"}, ticket)["state"], "wait")

    def test_the_lap_approves_the_plan_unless_the_ticket_is_high_risk(self):
        ticket, _ = self.load()
        self.assertEqual(tr.validate(dict(READY), ticket)["plan"], "lap")
        ticket["risk"] = "high"
        out = tr.validate(dict(READY), ticket)
        self.assertEqual(out["plan"], "human")
        self.assertIn('risk = "high"', out["rationale"][-1])

    # ---- freshness

    def test_a_new_decision_is_fresh(self):
        rec = self.record()
        self.assertEqual(rec["prereqs_done"], [])
        self.assertEqual(self.fresh(), (True, ""))

    def test_a_change_outside_touches_keeps_it_fresh(self):
        self.record()
        self.write("frontend/app.ts", "y\n")
        self.commit("frontend")
        self.assertEqual(self.fresh(), (True, ""))

    def test_a_change_in_touches_makes_it_stale(self):
        self.record()
        self.write("backend/link/Slugs.java", "class Slugs {}\n")
        self.commit("story 1 merged")
        fresh, why = self.fresh()
        self.assertFalse(fresh)
        self.assertIn("backend/link/Slugs.java", why)

    def test_a_refined_ticket_makes_it_stale(self):
        self.record()
        self.write(f"{TICKETS}/tickets.toml", TOML.format(desc="Adds custom slugs, lower case only.", risk="medium"))
        self.commit("refine 2")
        self.assertEqual(self.fresh(), (False, "the ticket, its leaf file or its epic file changed since"))

    def test_a_changed_epic_file_or_new_leaf_file_makes_it_stale(self):
        self.record()
        self.write(EPIC_FILE, "# Links\n\nDecision: slugs are lower case.\n")
        self.commit("decision")
        self.assertFalse(self.fresh()[0])
        tr._cache.clear()
        self.record()
        self.write(f"{TICKETS}/story-second.md", "---\nid: 2\nrefined: true\n---\n# Second\n")
        self.commit("pull 2")
        self.assertFalse(self.fresh()[0])

    def test_a_prerequisite_done_makes_it_stale(self):
        self.record()
        self.write(f"{TICKETS}/story-first-plan.md", "---\nticket: 1\nstatus: done\n---\n")
        self.commit("mark 1 done")
        self.assertEqual(self.fresh(), (False, "a prerequisite was done since"))

    def test_without_touches_any_code_change_makes_it_stale(self):
        self.write(f"{TICKETS}/tickets.toml", TOML.format(desc="x", risk="").replace(
            'touches = ["backend/link/**", "e2e/tests/1-2-*.spec.ts"]', ""))
        self.commit("no touches")
        self.record()
        self.write("docs/triage/1.json", "{}")
        self.commit("another decision")
        self.assertTrue(self.fresh()[0])
        self.write("frontend/app.ts", "z\n")
        self.commit("code")
        self.assertFalse(self.fresh()[0])

    # ---- the command line

    def run_cli(self, *args):
        script = str(Path(tr.__file__).resolve())
        done = subprocess.run([sys.executable, script, "2", "--rev", "main", *args], cwd=self.root,
                              capture_output=True, text=True, encoding="utf-8")
        return done.returncode, done.stdout

    def test_check_and_record_from_the_command_line(self):
        self.assertEqual(self.run_cli("check")[1].splitlines()[0], "none")
        answer = self.root / ".lap" / "2-triage.json"
        answer.parent.mkdir()
        answer.write_text("Here it is:\n" + json.dumps(READY), encoding="utf-8")
        code, out = self.run_cli("record", str(answer))
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "docs/triage/2.json").exists())
        self.assertEqual(self.run_cli("check")[1].splitlines()[0], "none")  # not on main until committed
        self.commit("triage 2")
        lines = self.run_cli("check")[1].splitlines()
        self.assertEqual(lines[:2], ["fresh ready-to-implement", "plan: the lap approves it"])

    def test_record_push_commits_onto_main_and_leaves_the_checkout_alone(self):
        origin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, origin, ignore_errors=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        self.git("remote", "add", "origin", str(origin))
        self.git("push", "-q", "origin", "main")
        answer = self.root / "answer.json"
        answer.write_text(json.dumps(READY), encoding="utf-8")
        script = str(Path(tr.__file__).resolve())
        done = subprocess.run([sys.executable, script, "2", "record", str(answer), "--push"], cwd=self.root,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("recorded ready-to-implement for 2 on main at", done.stdout)
        self.assertFalse((self.root / "docs/triage/2.json").exists())  # nothing written in this checkout
        self.assertEqual(self.git("worktree", "list").count("\n"), 1)  # the throwaway worktree is gone
        self.git("fetch", "-q", "origin")
        self.assertIn("Triage ticket 2: ready-to-implement", self.git("log", "-1", "--format=%B", "origin/main"))
        ticket, plans = tr._load(str(self.root), "origin/main", "2")
        rec = tr.read_record(str(self.root), "origin/main", "2")
        self.assertEqual(tr.freshness(str(self.root), "origin/main", rec, ticket, plans), (True, ""))

    def test_record_push_refuses_another_rev(self):
        answer = self.root / "answer.json"
        answer.write_text(json.dumps(READY), encoding="utf-8")
        code, out = self.run_cli("record", str(answer), "--push")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("refused: --push records against origin/main"))

    def test_record_refuses_a_bad_decision(self):
        answer = self.root / "bad.json"
        answer.write_text(json.dumps({"state": "needs-info", "summary": "x"}), encoding="utf-8")
        code, out = self.run_cli("record", str(answer))
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("refused: needs-info needs at least one question"))

    def test_statuses_lists_every_decision(self):
        self.record()
        ticket, plans = self.load()
        first, _ = tr._load(str(self.root), "main", "1")
        out = tr.statuses(str(self.root), "main", [first, ticket], plans)
        self.assertEqual(list(out), ["2"])
        self.assertEqual((out["2"]["state"], out["2"]["fresh"], out["2"]["plan"]), ("ready-to-implement", True, "lap"))
        self.assertEqual((out["2"]["rationale"], out["2"]["next_step"]), (["link/ has it"], "Run the lap."))

    def test_the_board_reads_decisions_from_origin_main(self):
        import board
        self.record()
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        ticket, plans = self.load()
        problems = []
        out = board.triage_statuses(str(self.root), [ticket], plans, problems)
        self.assertEqual((list(out), out["2"]["fresh"], problems), (["2"], True, []))

    def test_the_board_says_when_decisions_cannot_be_read(self):
        import board
        ticket, plans = self.load()
        problems = []
        self.assertEqual(board.triage_statuses(str(self.root / "missing"), [ticket], plans, problems), {})
        self.assertEqual(len(problems), 1)
        self.assertIn("triage decisions cannot be read", problems[0])


if __name__ == "__main__":
    unittest.main()
