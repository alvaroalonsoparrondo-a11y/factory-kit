"""Tests of the guards and the factory judge, with GitHub faked. Human-owned.

Run: python -m unittest discover -s harness/judge -v
"""
import io
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import classify
import guards
import judge as j

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/judge-guards.yml"


class GuardTests(unittest.TestCase):
    def test_protected_path_fails_without_label(self):
        passed, hits, _ = guards.judge("protected-paths", ["harness/run-gates.sh", "backend/App.java"])
        self.assertFalse(passed)
        self.assertEqual(hits, ["harness/run-gates.sh"])

    def test_label_allows_it(self):
        passed, hits, msg = guards.judge("protected-paths", ["CLAUDE.md"], ["human-judge-change"])
        self.assertTrue(passed)
        self.assertEqual(hits, ["CLAUDE.md"])
        self.assertIn("allowed by label", msg)

    def test_rename_out_of_a_protected_path_counts(self):
        files = [{"filename": "docs/x.sh", "previous_filename": "harness/x.sh"}]
        self.assertFalse(guards.judge("protected-paths", files)[0])
        self.assertTrue(guards.judge("scope-guard", [{"filename": "docs/x", "previous_filename": "a/jwt.txt"}])[0])

    def test_protected_paths_is_case_sensitive_and_anchored(self):
        self.assertTrue(guards.judge("protected-paths", ["docs/harness/x", "mission.md", "backend/CLAUDE.md"])[0])
        for path in ("MISSION.md", "AGENTS.md", ".github/workflows/x.yml", ".claude/settings.json",
                     ".claude/skills/lap/SKILL.md", ".kiro/agents/factory.json", ".kiro/skills/lap/SKILL.md",
                     ".claude/skills/triage/SKILL.md", ".kiro/skills/triage/SKILL.md",
                     "_bmad/custom/bmad-build.toml", "FACTORY_RULES.md"):
            self.assertFalse(guards.judge("protected-paths", [path])[0], path)

    def test_scope_guard_ignores_case(self):
        for path in ("backend/src/main/resources/db/migration/V1.sql", "backend/Security/Config.java",
                     "certs/key.PEM", "Dockerfile", "infra/terraform/main.tf", "src/auth/Login.ts"):
            self.assertFalse(guards.judge("scope-guard", [path])[0], path)
        self.assertTrue(guards.judge("scope-guard", ["backend/src/main/java/Shortlink.java"])[0])
        self.assertTrue(guards.judge("scope-guard", ["Dockerfile"], ["human-approved-irreversible"])[0])

    def test_template_skips_only_protected_paths(self):
        self.assertTrue(guards.judge("protected-paths", ["harness/x"], template=True)[0])
        self.assertFalse(guards.judge("scope-guard", ["Dockerfile"], template=True)[0])

    def test_description_fits_a_commit_status(self):
        passed, hits, msg = guards.judge("protected-paths", [f"harness/{'x' * 60}{n}" for n in range(5)])
        text = guards.description(passed, hits, msg)
        self.assertLessEqual(len(text), 140)
        self.assertTrue(text.startswith("5 hit(s)"))

    def test_cli_exit_codes(self):
        import sys
        for stdin, code in (("backend/A.java\n", 0), ("harness/x\n", 1)):
            sys.stdin, out = io.StringIO(stdin), io.StringIO()
            try:
                with redirect_stdout(out):
                    self.assertEqual(guards.main(["protected-paths"]), code)
            finally:
                sys.stdin = sys.__stdin__

    def test_the_workflow_calls_guards_py_and_holds_no_pattern_of_its_own(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for check in guards.CHECKS:
            self.assertIn(f"harness/judge/guards.py {check}", text)
        self.assertNotIn("grep -E", text)
        self.assertNotRegex(text, re.compile(r"liquibase|_bmad/custom"))


class FakeGitHub:
    def __init__(self, pulls, files, statuses=None, template=False, broken=()):
        self.pulls, self.files, self.template, self.broken = pulls, files, template, set(broken)
        self.statuses = statuses or {}
        self.posts = []

    def get(self, path, key=None):
        if path == "":
            return {"is_template": self.template}
        if path == "/pulls?state=open":
            return self.pulls
        if path.startswith("/pulls/"):
            number = int(path.split("/")[2])
            if number in self.broken:
                raise RuntimeError("HTTP 502")
            return self.files[number]
        if path.startswith("/issues/") and path.endswith("/events"):
            return getattr(self, "events", {}).get(int(path.split("/")[2]), [])
        if path.startswith("/issues/"):
            return self._comments().get(int(path.split("/")[2]), [])
        if path.startswith("/commits/"):
            sha = path.split("/")[2]
            return {"statuses": list(self.statuses.get(sha, {}).values())}
        raise AssertionError(path)

    def post_status(self, sha, context, state, description):
        self.posts.append((sha, context, state))
        self.statuses.setdefault(sha, {})[context] = {"context": context, "state": state, "description": description}

    comments = None

    def _comments(self):
        if self.comments is None:
            self.comments = {}
        return self.comments

    def post_comment(self, number, body):
        c = self._comments().setdefault(number, [])
        c.append({"id": 100 * number + len(c), "body": body})

    def edit_comment(self, comment_id, body):
        for cs in self._comments().values():
            for c in cs:
                if c["id"] == comment_id:
                    c["body"] = body


def pr(number, sha, labels=()):
    return {"number": number, "head": {"sha": sha}, "labels": [{"name": n} for n in labels]}


class JudgeTests(unittest.TestCase):
    def judge(self, gh, dry_run=False):
        lines = []
        return j.Judge(gh, dry_run=dry_run, out=lines.append), lines

    def test_posts_both_guards_for_each_pull_request(self):
        gh = FakeGitHub([pr(1, "a" * 40), pr(2, "b" * 40)],
                        {1: [{"filename": "backend/A.java"}], 2: [{"filename": "harness/run-gates.sh"}]})
        self.judge(gh)[0].run_pass()
        self.assertEqual(sorted(gh.posts), [("a" * 40, "protected-paths", "success"), ("a" * 40, "scope-guard", "success"),
                                            ("b" * 40, "protected-paths", "failure"), ("b" * 40, "scope-guard", "success")])

    def test_an_unchanged_status_is_not_posted_again(self):
        gh = FakeGitHub([pr(1, "a" * 40)], {1: [{"filename": "harness/x"}]})
        jd, _ = self.judge(gh)
        jd.run_pass()
        self.assertEqual(jd.run_pass(), [])
        self.assertEqual(len(gh.posts), 2)

    def test_a_label_turns_the_guard_green_on_the_next_pass(self):
        pulls = [pr(1, "a" * 40)]
        gh = FakeGitHub(pulls, {1: [{"filename": "harness/x"}]})
        jd, _ = self.judge(gh)
        jd.run_pass()
        pulls[0] = pr(1, "a" * 40, ["human-judge-change"])
        self.assertEqual(jd.run_pass(), [(1, "protected-paths", "success")])

    def test_a_faked_green_on_a_protected_change_is_overwritten(self):
        sha = "a" * 40
        gh = FakeGitHub([pr(1, sha)], {1: [{"filename": "harness/x"}]},
                        statuses={sha: {"protected-paths": {"context": "protected-paths", "state": "success",
                                                            "description": "No protected-paths hit in the changed paths."}}})
        self.judge(gh)[0].run_pass()
        self.assertIn((sha, "protected-paths", "failure"), gh.posts)

    def test_template_repository(self):
        gh = FakeGitHub([pr(1, "a" * 40)], {1: [{"filename": "harness/x"}]}, template=True)
        self.judge(gh)[0].run_pass()
        self.assertIn(("a" * 40, "protected-paths", "success"), gh.posts)

    def test_dry_run_posts_nothing(self):
        gh = FakeGitHub([pr(1, "a" * 40)], {1: [{"filename": "harness/x"}]})
        jd, lines = self.judge(gh, dry_run=True)
        self.assertEqual(len(jd.run_pass()), 2)
        self.assertEqual(gh.posts, [])
        self.assertTrue(all("would post" in line for line in lines if line.startswith("#")))
        self.assertIn("2 guard status(es) to post", lines[-1])

    def test_one_failing_pull_request_does_not_stop_the_others(self):
        gh = FakeGitHub([pr(1, "a" * 40), pr(2, "b" * 40)], {2: [{"filename": "backend/A.java"}]}, broken=[1])
        jd, lines = self.judge(gh)
        jd.run_pass()
        self.assertEqual({p[0] for p in gh.posts}, {"b" * 40})
        self.assertTrue(any("#1: not judged" in line for line in lines))


class ClassifyTests(unittest.TestCase):
    def test_machine_failures_need_evidence(self):
        for line, kind in (("npm ERR! code ETIMEDOUT", "network"),
                           ("[ERROR] Could not transfer artifact org.x:y:pom:1 from/to central (https://repo)", "network"),
                           ("java.net.UnknownHostException: repo.maven.apache.org", "network"),
                           ("Web server failed to start. Port 8190 was already in use.", "port"),
                           ("bash: mvn: command not found", "tool"),
                           ("write error: No space left on device", "disk"),
                           ("Failed to download Chromium 120", "browser"),
                           ("Windows Subsystem for Linux has no installed distributions.", "tool"),
                           ("bash: command not found. The judge needs bash; on Windows, Git for Windows.", "tool")):
            cause, evidence = classify.classify(f"== Gate 1\n{line}\nmore\n")
            self.assertEqual(cause, "environment", line)
            self.assertTrue(evidence.startswith(kind), evidence)

    def test_failures_the_change_can_cause_are_introduced(self):
        for line in ("[ERROR] Tests run: 12, Failures: 1", "error TS2339: Property 'x' does not exist",
                     "connect ECONNREFUSED 127.0.0.1:8190", "GATE FAIL: build identity mismatch",
                     "GATE FAIL: application did not become healthy", "1 failed: shortlink.spec.ts"):
            self.assertEqual(classify.classify(line)[0], "introduced", line)

    def test_main_and_timeout(self):
        self.assertEqual(classify.classify("Failures: 1", main_red=True)[0], "inherited")
        self.assertEqual(classify.classify("Failures: 1", main_red=False)[0], "introduced")
        self.assertEqual(classify.classify("x\n" + classify.TIMEOUT + " in 30 minutes.")[0], "timeout")
        self.assertEqual(classify.classify("bash: npm: command not found", main_red=True)[0], "environment")


class FindBashTests(unittest.TestCase):
    """The gate's bash on Windows is never WSL's or the Store's stand-in (factory-kit#12)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def file(self, rel):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        return str(path)

    @unittest.skipUnless(os.name == "nt", "the Windows search order")
    def test_wsl_bash_on_path_is_skipped_for_gits_bash(self):
        wsl = self.file("Windows/System32/bash.exe")
        git = self.file("Git/cmd/git.exe")
        gits = self.file("Git/usr/bin/bash.exe")
        found = j.find_bash(lambda name: {"bash": wsl, "git": git}[name])
        self.assertEqual(Path(found), Path(gits).resolve())

    @unittest.skipUnless(os.name == "nt", "the Windows search order")
    def test_git_bash_first_on_path_is_used(self):
        gits = self.file("Git/usr/bin/bash.exe")
        self.assertEqual(j.find_bash(lambda name: gits if name == "bash" else None), gits)

    @unittest.skipUnless(os.name == "nt", "the Windows search order")
    def test_only_stand_ins_means_no_bash(self):
        store = self.file("Users/me/AppData/Local/Microsoft/WindowsApps/bash.exe")
        self.assertIsNone(j.find_bash(lambda name: store if name == "bash" else None))

    def test_the_real_bash_runs(self):
        bash = j.find_bash()
        self.assertIsNotNone(bash)
        done = subprocess.run([bash, "-c", "echo ok"], capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), "ok")


MAIN = "f" * 40


class FakeWorkspace:
    """Git and the gate run, faked: `codes` gives each head's exit code (None is a timeout)."""

    def __init__(self, codes=None, conflicts=(), main=MAIN):
        self.codes, self.conflicts, self.main = codes or {}, set(conflicts), main
        self.folder = Path(tempfile.mkdtemp())
        self.runs, self.cleaned, self.heads = [], [], {}

    def fetch(self):
        return self.main

    def fetch_pull(self, number):
        return self.heads.get(number) or self._head[number]

    def prepare(self, main, head=None):
        if head in self.conflicts:
            raise j.Conflict("CONFLICT")
        return self.folder / (head or main)[:12]

    def run(self, path, candidate, port, log, timeout):
        sha = candidate.split("-judge-")[0]
        self.runs.append(sha)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(getattr(self, "logs", {}).get(sha, f"output of {sha[:7]}\nGATE FAIL: something\n"))
        return self.codes.get(sha, 0), 125

    def cleanup(self, path):
        self.cleaned.append(path)


class GatesTests(unittest.TestCase):
    def setup(self, pulls, codes=None, conflicts=()):
        gh = FakeGitHub(pulls, {p["number"]: [{"filename": "backend/A.java"}] for p in pulls})
        ws = FakeWorkspace(codes, conflicts)
        ws._head = {p["number"]: p["head"]["sha"] for p in pulls}
        lines = []
        return gh, ws, j.Judge(gh, ws=ws, out=lines.append), lines

    def gates(self, gh, sha):
        return [p[2] for p in gh.posts if p[0] == sha and p[1] == "gates"]

    def test_an_unjudged_pull_request_gets_pending_then_its_result(self):
        gh, ws, jd, _ = self.setup([pr(1, "a" * 40)])
        jd.run_pass()
        self.assertEqual(ws.runs, ["a" * 40])
        self.assertEqual(self.gates(gh, "a" * 40), ["pending", "success"])
        self.assertIn("Passed on the merge with main fffffff", gh.statuses["a" * 40]["gates"]["description"])
        self.assertEqual(len(ws.cleaned), 1)

    def test_one_gate_run_per_pass_oldest_first_then_main(self):
        gh, ws, jd, _ = self.setup([pr(7, "b" * 40), pr(3, "a" * 40)])
        jd.run_pass()
        self.assertEqual(ws.runs, ["a" * 40])
        jd.run_pass()
        jd.run_pass()
        self.assertEqual(ws.runs, ["a" * 40, "b" * 40, MAIN])
        jd.run_pass()
        self.assertEqual(len(ws.runs), 3)  # each commit is judged once

    def test_a_failure_is_red_with_the_log_tail_in_one_comment(self):
        gh, ws, jd, _ = self.setup([pr(1, "a" * 40)], codes={"a" * 40: 1})
        jd.run_pass()
        self.assertEqual(self.gates(gh, "a" * 40), ["pending", "failure"])
        (c,) = gh.comments[1]
        self.assertIn(j.MARKER, c["body"])
        self.assertIn(f"<!-- sha:{'a' * 40} -->", c["body"])
        self.assertIn("GATE FAIL: something", c["body"])

    def test_the_next_commit_edits_the_same_comment(self):
        pulls = [pr(1, "a" * 40)]
        gh, ws, jd, _ = self.setup(pulls, codes={"a" * 40: 1})
        jd.run_pass()
        pulls[0] = pr(1, "c" * 40)
        ws._head[1] = "c" * 40
        jd.run_pass()
        (c,) = gh.comments[1]
        self.assertIn("**gates** passed on `ccccccc`", c["body"])

    def test_a_pass_with_no_failure_writes_no_comment(self):
        gh, ws, jd, _ = self.setup([pr(1, "a" * 40)])
        jd.run_pass()
        self.assertFalse(gh.comments)

    def test_a_timeout_is_red(self):
        gh, ws, jd, _ = self.setup([pr(1, "a" * 40)], codes={"a" * 40: None})
        jd.run_pass()
        self.assertEqual(self.gates(gh, "a" * 40)[-1], "failure")
        self.assertIn("Stopped after 30 min", gh.statuses["a" * 40]["gates"]["description"])

    def test_a_faked_gates_status_is_overwritten_without_running_again(self):
        gh, ws, jd, _ = self.setup([pr(1, "a" * 40)], codes={"a" * 40: 1})
        jd.run_pass()
        gh.statuses["a" * 40]["gates"] = {"context": "gates", "state": "success", "description": "trust me"}
        jd.run_pass()
        self.assertEqual(gh.statuses["a" * 40]["gates"]["state"], "failure")
        self.assertEqual(ws.runs.count("a" * 40), 1)

    def test_a_conflict_gets_no_status_and_waits_for_main_to_move(self):
        gh, ws, jd, lines = self.setup([pr(1, "a" * 40)], conflicts=["a" * 40])
        jd.run_pass()
        self.assertEqual(self.gates(gh, "a" * 40), [])
        self.assertTrue(any("conflicts with main" in line for line in lines))
        jd.run_pass()  # not tried again on the same main: main itself runs instead
        self.assertEqual(ws.runs, [MAIN])
        ws.main = "e" * 40
        ws.conflicts.clear()
        jd.run_pass()
        self.assertEqual(ws.runs, [MAIN, "a" * 40])

    def test_a_head_that_moved_is_left_for_the_next_pass(self):
        gh, ws, jd, lines = self.setup([pr(1, "a" * 40)])
        ws.heads[1] = "d" * 40
        jd.run_pass()
        self.assertEqual(ws.runs, [])
        self.assertTrue(any("moved while judging" in line for line in lines))

    def test_dry_run_runs_nothing(self):
        gh, ws, _, _ = self.setup([pr(1, "a" * 40)])
        lines = []
        j.Judge(gh, ws=ws, dry_run=True, out=lines.append).run_pass()
        self.assertEqual((ws.runs, gh.posts), ([], []))
        self.assertTrue(any("would run gates" in line for line in lines))

    def test_on_demand_for_one_pull_request(self):
        gh, ws, _, _ = self.setup([pr(3, "a" * 40), pr(5, "b" * 40)])
        lines = []
        jd = j.Judge(gh, ws=ws, out=lines.append, only=5)
        jd.drain()
        self.assertEqual(ws.runs, ["b" * 40])  # not #3, and not main
        self.assertEqual({p[0] for p in gh.posts}, {"b" * 40})
        ok, line = jd.verdict(5)
        self.assertTrue(ok)
        self.assertIn("gates success", line)
        self.assertIn("Ready for your review", line)

    def test_on_demand_red_is_not_ready(self):
        gh, ws, _, _ = self.setup([pr(5, "b" * 40)], codes={"b" * 40: 1})
        jd = j.Judge(gh, ws=ws, out=[].append, only=5)
        jd.drain()
        ok, line = jd.verdict(5)
        self.assertFalse(ok)
        self.assertIn("gates failure", line)

    def test_on_demand_for_a_pull_request_that_is_not_open(self):
        gh, ws, _, _ = self.setup([pr(3, "a" * 40)])
        lines = []
        jd = j.Judge(gh, ws=ws, out=lines.append, only=9)
        jd.drain()
        self.assertEqual(ws.runs, [])
        self.assertFalse(jd.verdict(9)[0])
        self.assertIn("#9 is not an open pull request", lines)

    def test_once_judges_everything_waiting_then_stops(self):
        gh, ws, jd, _ = self.setup([pr(3, "a" * 40), pr(5, "b" * 40)])
        jd.drain()
        self.assertEqual(ws.runs, ["a" * 40, "b" * 40, MAIN])

    def red_commits(self, gh, ws, jd, pulls, n):
        """Push n red commits to pull request #1, judging each."""
        for i in range(n):
            sha = f"{i:x}" * 40
            pulls[0] = pr(1, sha[:40])
            ws._head[1] = sha[:40]
            ws.codes[sha[:40]] = 1
            jd.run_pass()

    def test_the_round_budget_stops_judging_new_commits(self):
        pulls = [pr(1, "a" * 40)]
        gh, ws, jd, _ = self.setup(pulls)
        self.red_commits(gh, ws, jd, pulls, 3)
        self.assertEqual([r for r in ws.runs if r != MAIN], [f"{i:x}" * 40 for i in range(3)])
        self.assertEqual(ws.runs.count(MAIN), 1)  # judged once, to tell whether the red was inherited
        pulls[0] = pr(1, "e" * 40)
        ws._head[1] = "e" * 40
        jd.run_pass()
        self.assertNotIn("e" * 40, ws.runs)  # the fourth commit is not judged
        status = gh.statuses["e" * 40]["gates"]
        self.assertEqual(status["state"], "failure")
        self.assertIn("Round budget spent: 3 red gate runs of 3", status["description"])
        self.assertLessEqual(len(status["description"]), 140)

    def test_a_human_label_grants_one_more_round(self):
        pulls = [pr(1, "a" * 40)]
        gh, ws, jd, _ = self.setup(pulls)
        self.red_commits(gh, ws, jd, pulls, 3)
        gh.events = {1: [{"event": "labeled", "label": {"name": j.GRANT_LABEL}}]}
        pulls[0] = pr(1, "e" * 40)
        ws._head[1] = "e" * 40
        jd.run_pass()
        self.assertIn("e" * 40, ws.runs)
        self.assertEqual(gh.statuses["e" * 40]["gates"]["state"], "success")

    def test_a_timeout_does_not_spend_the_budget(self):
        pulls = [pr(1, "a" * 40)]
        gh, ws, jd, _ = self.setup(pulls)
        for i in range(3):
            sha = f"{i:x}" * 40
            pulls[0] = pr(1, sha)
            ws._head[1] = sha
            ws.codes[sha] = None
            jd.run_pass()
        self.assertEqual(jd.red_runs(1), 0)

    def test_other_pull_requests_have_their_own_budget(self):
        pulls = [pr(1, "a" * 40), pr(2, "b" * 40)]
        gh, ws, jd, _ = self.setup(pulls, codes={"b" * 40: 1})
        jd.only = 1
        self.red_commits(gh, ws, jd, pulls, 3)
        self.assertEqual((jd.red_runs(1), jd.red_runs(2)), (3, 0))

    def test_a_machine_failure_runs_again_then_stops_without_a_round(self):
        gh, ws, jd, lines = self.setup([pr(1, "a" * 40)], codes={"a" * 40: 1})
        ws.logs = {"a" * 40: "npm ERR! code ECONNRESET\nnpm ERR! network request failed\n"}
        jd.run_pass()
        self.assertEqual(self.gates(gh, "a" * 40), ["pending", "pending"])  # running, then: will run again
        self.assertIn("Machine failure (network", gh.statuses["a" * 40]["gates"]["description"])
        jd.run_pass()
        self.assertEqual(ws.runs.count("a" * 40), 2)
        status = gh.statuses["a" * 40]["gates"]
        self.assertEqual(status["state"], "error")
        self.assertTrue(status["description"].startswith(j.NOT_THIS_CHANGE))
        self.assertLessEqual(len(status["description"]), 140)
        self.assertEqual(jd.red_runs(1), 0)
        self.assertIn("Cause: **environment**", gh.comments[1][0]["body"])
        self.assertNotIn(MAIN, ws.runs)  # a machine failure needs no look at main
        jd.run_pass()
        self.assertEqual(ws.runs.count("a" * 40), 2)  # stopped: not run a third time

    def test_retry_errors_judges_it_again_once_the_machine_is_fixed(self):
        gh, ws, jd, _ = self.setup([pr(1, "a" * 40)], codes={"a" * 40: 1})
        ws.logs = {"a" * 40: "bash: java: command not found\n"}
        jd.run_pass()
        jd.run_pass()
        self.assertEqual(gh.statuses["a" * 40]["gates"]["state"], "error")
        ws.codes["a" * 40], ws.logs = 0, {}
        jd.retry_errors = True
        jd.run_pass()
        self.assertEqual(gh.statuses["a" * 40]["gates"]["state"], "success")

    def test_red_on_main_too_is_inherited_and_takes_no_round(self):
        gh, ws, jd, _ = self.setup([pr(1, "a" * 40)], codes={"a" * 40: 1, MAIN: 1})
        jd.run_pass()
        self.assertEqual(ws.runs, ["a" * 40, MAIN])  # main judged alone to decide
        status = gh.statuses["a" * 40]["gates"]
        self.assertEqual(status["state"], "failure")
        self.assertIn("red on main fffffff alone", status["description"])
        self.assertTrue(status["description"].startswith(j.NOT_THIS_CHANGE))
        self.assertEqual(jd.red_runs(1), 0)
        self.assertIn("Cause: **inherited**", gh.comments[1][0]["body"])
        self.assertEqual(gh.statuses[MAIN]["gates"]["state"], "failure")

    def test_red_with_main_green_is_introduced_and_takes_a_round(self):
        gh, ws, jd, _ = self.setup([pr(1, "a" * 40)], codes={"a" * 40: 1})
        jd.run_pass()
        self.assertEqual(jd.red_runs(1), 1)
        self.assertIn("Cause: **introduced**", gh.comments[1][0]["body"])
        self.assertIn("takes a round (`ci`)", gh.comments[1][0]["body"])
        pulls = gh.pulls
        pulls[0] = pr(1, "c" * 40)
        ws._head[1] = "c" * 40
        ws.codes["c" * 40] = 1
        jd.run_pass()
        self.assertEqual(ws.runs.count(MAIN), 1)  # main's verdict is reused, not run again

    def test_verdicts_survive_a_restart(self):
        folder = Path(tempfile.mkdtemp()) / ".factory" / "judge"
        v = j.Verdicts(folder / "verdicts.json")
        v.put("a" * 40, {"state": "success", "description": "ok"})
        self.assertEqual(j.Verdicts(folder / "verdicts.json").get("a" * 40)["state"], "success")
        self.assertEqual((folder.parent / ".gitignore").read_text(), "*\n")


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


GATE = """#!/usr/bin/env bash
cd "$(dirname "$0")/.."
env > gate-env.txt
grep -q good app.txt
"""


class WorkspaceTests(unittest.TestCase):
    """The real Git steps against a local origin; the gate is a tiny script."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        origin, seed = self.tmp / "origin.git", self.tmp / "seed"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.tmp, "init", "-q", "-b", "main", str(seed))
        for name, text in {"harness/run-gates.sh": GATE, "app.txt": "good\n", LAP_A: "lap\n", LAP_B: "lap\n"}.items():
            (seed / name).parent.mkdir(parents=True, exist_ok=True)
            (seed / name).write_text(text)
        self.commit(seed, "main")
        git(seed, "remote", "add", "origin", str(origin))
        git(seed, "push", "-q", "origin", "main")
        self.seed, self.origin = seed, origin
        self.clone = self.tmp / "judge-clone"
        git(self.tmp, "clone", "-q", str(origin), str(self.clone))
        self.ws = j.Workspace(self.clone, self.clone / ".factory" / "judge")

    def commit(self, repo, msg):
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)
        return git(repo, "rev-parse", "HEAD")

    def pull_request(self, number, files):
        git(self.seed, "switch", "-q", "-c", f"story/{number}", "main")
        for name, text in files.items():
            (self.seed / name).write_text(text)
        sha = self.commit(self.seed, f"pr {number}")
        git(self.seed, "push", "-q", "origin", f"HEAD:refs/pull/{number}/head")
        git(self.seed, "switch", "-q", "main")
        return sha

    def gate(self, head=None):
        main = self.ws.fetch()
        if head:
            self.assertEqual(self.ws.fetch_pull(1), head)
        path = self.ws.prepare(main, head)
        log = self.ws.folder / "logs" / "t.log"
        os.environ["GITHUB_TOKEN"] = "must-not-reach-the-gate"
        try:
            code, _ = self.ws.run(path, "cand", 8190, log, 60)
            env = (path / "gate-env.txt").read_text() if (path / "gate-env.txt").exists() else ""
        finally:
            del os.environ["GITHUB_TOKEN"]
            self.ws.cleanup(path)
        self.assertFalse(path.exists())
        return code, env, log.read_text()

    def test_the_judges_folder_leaves_the_clone_clean(self):
        self.gate()
        self.assertEqual(git(self.clone, "status", "--porcelain"), "")

    def test_main_passes_and_the_gate_sees_no_token(self):
        code, env, _ = self.gate()
        self.assertEqual(code, 0)
        self.assertIn("FACTORY_RUNTIME_CANDIDATE=cand", env)
        self.assertIn("PORT=8190", env)
        self.assertNotIn("must-not-reach-the-gate", env)

    def test_a_broken_pull_request_is_red(self):
        self.assertEqual(self.gate(self.pull_request(1, {"app.txt": "bad\n"}))[0], 1)

    def test_a_pull_request_cannot_change_the_gate_that_judges_it(self):
        head = self.pull_request(1, {"app.txt": "bad\n", "harness/run-gates.sh": "#!/usr/bin/env bash\nexit 0\n"})
        self.assertEqual(self.gate(head)[0], 1)

    def test_lap_skills_that_differ_are_red(self):
        code, _, log = self.gate(self.pull_request(1, {LAP_B: "changed\n"}))
        self.assertEqual(code, 1)
        self.assertIn("must be a copy of", log)

    def test_a_conflict_with_main_is_reported(self):
        head = self.pull_request(1, {"app.txt": "good, from the pull request\n"})
        (self.seed / "app.txt").write_text("good, from main\n")
        self.commit(self.seed, "main moves")
        git(self.seed, "push", "-q", "origin", "main")
        main = self.ws.fetch()
        self.ws.fetch_pull(1)
        with self.assertRaises(j.Conflict):
            self.ws.prepare(main, head)
        self.assertEqual(list((self.ws.folder / "work").iterdir()), [])

    def test_a_timeout_kills_the_gate(self):
        (self.seed / "harness/run-gates.sh").write_text("#!/usr/bin/env bash\nsleep 30\n")
        self.commit(self.seed, "slow gate")
        git(self.seed, "push", "-q", "origin", "main")
        main = self.ws.fetch()
        path = self.ws.prepare(main)
        log = self.ws.folder / "logs" / "slow.log"
        code, seconds = self.ws.run(path, "cand", 8190, log, 1)
        self.ws.cleanup(path)
        self.assertIsNone(code)
        self.assertLess(seconds, 10)
        self.assertIn("GATE STOPPED", log.read_text())


LAP_A, LAP_B = j.LAP_SKILLS


if __name__ == "__main__":
    unittest.main()
