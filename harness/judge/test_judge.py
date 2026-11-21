"""Tests of the guards and the factory judge, with GitHub faked. Human-owned.

Run: python -m unittest discover -s harness/judge -v
"""
import io
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path

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
        if path.startswith("/commits/"):
            sha = path.split("/")[2]
            return {"statuses": list(self.statuses.get(sha, {}).values())}
        raise AssertionError(path)

    def post_status(self, sha, context, state, description):
        self.posts.append((sha, context, state))
        self.statuses.setdefault(sha, {})[context] = {"context": context, "state": state, "description": description}


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
        self.assertIn("2 status(es) to post", lines[-1])

    def test_one_failing_pull_request_does_not_stop_the_others(self):
        gh = FakeGitHub([pr(1, "a" * 40), pr(2, "b" * 40)], {2: [{"filename": "backend/A.java"}]}, broken=[1])
        jd, lines = self.judge(gh)
        jd.run_pass()
        self.assertEqual({p[0] for p in gh.posts}, {"b" * 40})
        self.assertTrue(any("#1: not judged" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
