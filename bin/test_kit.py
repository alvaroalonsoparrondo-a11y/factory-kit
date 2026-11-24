"""Tests of kit.py, against scratch Git repositories. Human-owned.

Run: python -m unittest discover -s bin -v
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit  # noqa: E402

REAL = HERE.parent
ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args, when=None):
    env = dict(os.environ, **ENV)
    if when is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"@{1_700_000_000 + when} +0000"
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env)
    if done.returncode:
        raise AssertionError(f"git {args}: {done.stderr}")
    return done.stdout.strip()


def commit_all(cwd, message, when=None):
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", message, when=when)
    return git(cwd, "rev-parse", "HEAD")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.kit = self.tmp / "factory-kit"
        for folder in ("template", "seed", "bin"):
            shutil.copytree(REAL / folder, self.kit / folder, ignore=shutil.ignore_patterns("__pycache__"))
        git(self.tmp, "init", "-q", "-b", "main", str(self.kit))
        git(self.kit, "config", "core.autocrlf", "false")
        commit_all(self.kit, "kit", when=1_000_000)
        self.proj = self.tmp / "shop"
        git(self.tmp, "init", "-q", "-b", "main", str(self.proj))
        git(self.proj, "config", "core.autocrlf", "false")
        (self.proj / "app.txt").write_text("product\n")
        commit_all(self.proj, "product", when=1_000_100)

    def run_kit(self, *args):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = kit.main(["--kit", str(self.kit), "--project", str(self.proj), *args])
        return code, buf.getvalue() + err.getvalue()

    def init(self, when=1_000_200):
        code, text = self.run_kit("init", "--owner", "alice")
        self.assertEqual(code, 0, text)
        commit_all(self.proj, "factory", when=when)

    def kit_change(self, rel, text, when):
        p = self.kit / "template" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return commit_all(self.kit, f"kit changes {rel}", when=when)

    def merge_sync(self, when):
        """Commit what sync wrote and merge it into main, as the pull request would."""
        branch = git(self.proj, "rev-parse", "--abbrev-ref", "HEAD")
        commit_all(self.proj, "sync", when=when)
        git(self.proj, "switch", "-q", "main")
        git(self.proj, "merge", "-q", "--no-ff", branch, "-m", "merge sync", when=when)
        git(self.proj, "branch", "-q", "-D", branch)

    def text(self, rel):
        return (self.proj / rel).read_text()


class InitTests(Base):
    def test_init_installs_a_project_doctor_passes(self):
        self.init()
        self.assertTrue((self.proj / "kit.lock.json").is_file())
        self.assertTrue((self.proj / "harness/judge/judge.py").is_file())
        self.assertIn("@alice", self.text(".github/CODEOWNERS"))
        self.assertIn("# shop", self.text("README.md"))
        self.assertNotIn("__", self.text("README.md").split("\n")[0])
        self.assertIn("Edit(/kit.lock.json)", self.text(".claude/settings.json"))
        self.assertEqual(self.run_kit("doctor")[0], 0)

    def test_init_refuses_an_existing_factory(self):
        self.init()
        code, text = self.run_kit("init", "--owner", "alice")
        self.assertEqual(code, 2)
        self.assertIn("already has the factory", text)

    def test_a_noop_sync_changes_nothing(self):
        self.init()
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)
        self.assertIn("nothing to do", text)
        self.assertEqual(git(self.proj, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertNotIn("factory/sync-", git(self.proj, "branch"))
        self.assertEqual(git(self.proj, "status", "--porcelain"), "")


class LocalChangeTests(Base):
    def setUp(self):
        super().setUp()
        self.init()

    def test_kit_change_replaces_the_file(self):
        self.kit_change("RUNBOOK.md", "new runbook\n", when=1_000_300)
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.text("RUNBOOK.md"), "new runbook\n")
        self.assertTrue(git(self.proj, "rev-parse", "--abbrev-ref", "HEAD").startswith("factory/sync-"))
        lock = json.loads(self.text("kit.lock.json"))
        self.assertEqual(lock["revision"], git(self.kit, "rev-parse", "HEAD"))

    def test_project_only_change_is_kept_and_listed(self):
        (self.proj / "RUNBOOK.md").write_text("mine\n")
        commit_all(self.proj, "project fix", when=1_000_300)
        self.kit_change("MODIFYING.md", "kit moved on\n", when=1_000_400)
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.text("RUNBOOK.md"), "mine\n")
        self.assertIn("not in the kit yet: RUNBOOK.md", text)

    def test_carried_over_change_only_updates_the_lock(self):
        (self.proj / "RUNBOOK.md").write_text("fixed\n")
        commit_all(self.proj, "project fix", when=1_000_300)
        self.kit_change("RUNBOOK.md", "fixed\n", when=1_000_400)
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.text("RUNBOOK.md"), "fixed\n")
        self.assertNotIn("not in the kit yet", text)
        self.merge_sync(when=1_000_500)
        self.assertIn("nothing to do", self.run_kit("sync")[1])

    def test_both_changed_the_kit_reached_main_later(self):
        (self.proj / "RUNBOOK.md").write_text("mine\n")
        commit_all(self.proj, "project fix", when=1_000_300)
        self.kit_change("RUNBOOK.md", "kit's\n", when=1_000_400)
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.text("RUNBOOK.md"), "kit's\n")
        self.assertIn("the kit's change reached main later", text)

    def test_both_changed_a_fix_written_early_but_merged_late_wins(self):
        git(self.proj, "switch", "-q", "-c", "fix")
        (self.proj / "RUNBOOK.md").write_text("mine\n")
        commit_all(self.proj, "written early", when=1_000_300)
        self.kit_change("RUNBOOK.md", "kit's\n", when=1_000_400)
        git(self.proj, "switch", "-q", "main")
        git(self.proj, "merge", "-q", "--no-ff", "fix", "-m", "merged late", when=1_000_500)
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.text("RUNBOOK.md"), "mine\n")
        self.assertIn("the project's change reached main later", text)

    def test_discard_takes_the_kits_version(self):
        (self.proj / "RUNBOOK.md").write_text("mine\n")
        commit_all(self.proj, "project fix", when=1_000_300)
        self.kit_change("MODIFYING.md", "kit moved on\n", when=1_000_400)
        code, text = self.run_kit("sync", "--discard", "RUNBOOK.md")
        self.assertEqual(code, 0, text)
        self.assertEqual(normal_text(self.text("RUNBOOK.md")),
                         normal_text((self.kit / "template/RUNBOOK.md").read_text()))

    def test_project_files_and_seeds_are_never_written_after_init(self):
        (self.proj / "MISSION.md").write_text("our mission\n")
        commit_all(self.proj, "mission", when=1_000_300)
        (self.kit / "seed/MISSION.md").write_text("new template mission\n")
        commit_all(self.kit, "seed changes", when=1_000_400)
        self.run_kit("sync")
        self.assertEqual(self.text("MISSION.md"), "our mission\n")

    def test_kit_removes_a_file(self):
        (self.kit / "template/harness/rounds.json").unlink()
        commit_all(self.kit, "drop rounds", when=1_000_300)
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)
        self.assertFalse((self.proj / "harness/rounds.json").exists())

    def test_kit_removes_a_workflow(self):  # issue #40: board.yml must leave projects that have it
        wf = self.kit / "template/.github/workflows"
        victim = sorted(wf.glob("*.yml"))[0].name
        self.assertTrue((self.proj / ".github/workflows" / victim).exists())
        (wf / victim).unlink()
        commit_all(self.kit, "drop a workflow", when=1_000_300)
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)
        self.assertFalse((self.proj / ".github/workflows" / victim).exists())
        self.assertTrue((self.proj / ".github/CODEOWNERS").exists())
        lock = json.loads((self.proj / "kit.lock.json").read_text())
        self.assertNotIn(f".github/workflows/{victim}", lock["files"])


class FenceTests(Base):
    def setUp(self):
        super().setUp()
        self.init()

    def deny(self, root):
        return json.loads((root / ".claude/settings.json").read_text())["permissions"]["deny"]

    def test_kit_entries_added_and_dropped_project_entries_and_settings_kept(self):
        settings = json.loads(self.text(".claude/settings.json"))
        settings["permissions"]["deny"].append("Edit(/src/secret/**)")
        settings["model"] = "opus"
        (self.proj / ".claude/settings.json").write_text(json.dumps(settings, indent=2))
        commit_all(self.proj, "own rule", when=1_000_300)
        kit_settings = json.loads((self.kit / "template/.claude/settings.json").read_text())
        kit_settings["permissions"]["deny"].remove("Bash(git push -f*)")
        kit_settings["permissions"]["deny"].append("Bash(git reset --hard*)")
        self.kit_change(".claude/settings.json", json.dumps(kit_settings, indent=2), when=1_000_400)
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)
        deny = self.deny(self.proj)
        self.assertIn("Edit(/src/secret/**)", deny)
        self.assertIn("Bash(git reset --hard*)", deny)
        self.assertNotIn("Bash(git push -f*)", deny)
        self.assertEqual(json.loads(self.text(".claude/settings.json"))["model"], "opus")

    def test_kiro_fence_merge(self):
        kiro = json.loads((self.kit / "template/.kiro/agents/factory.json").read_text())
        kiro["permissions"]["rules"][0]["match"].append("NEW.md")
        self.kit_change(".kiro/agents/factory.json", json.dumps(kiro, indent=2), when=1_000_300)
        self.run_kit("sync")
        mine = json.loads(self.text(".kiro/agents/factory.json"))
        self.assertIn("NEW.md", mine["permissions"]["rules"][0]["match"])
        self.assertEqual(mine["permissions"]["rules"][0]["match"].count("NEW.md"), 1)

    def test_doctor_fails_when_a_protected_path_is_not_denied(self):
        settings = json.loads(self.text(".claude/settings.json"))
        settings["permissions"]["deny"].remove("Edit(/harness/**)")
        (self.proj / ".claude/settings.json").write_text(json.dumps(settings))
        code, text = self.run_kit("doctor")
        self.assertEqual(code, 1)
        self.assertIn("Edit(/harness/**)", text)

    def test_doctor_warns_on_codeowners_and_fails_on_lap_skills(self):
        (self.proj / ".github/CODEOWNERS").write_text("/MISSION.md @alice\n")
        code, text = self.run_kit("doctor")
        self.assertEqual(code, 0, text)
        self.assertIn("warning: .github/CODEOWNERS has no line for /harness/", text)
        self.assertIn("add the line `/harness/ @alice`", text)
        (self.proj / ".kiro/skills/lap/SKILL.md").write_text("drifted\n")
        self.assertEqual(self.run_kit("doctor")[0], 1)


class SetupTests(Base):
    """`doctor` lists what the one-time setup still lacks, and never fails on it (factory-pilot-2, item 1)."""

    def setUp(self):
        super().setUp()
        self.init()
        git(self.proj, "remote", "add", "origin", "https://github.com/alice/shop.git")
        self.answers = {
            "repos/alice/shop/actions/permissions": (200, {"enabled": True}),
            "repos/alice/shop/labels?per_page=100": (200, [{"name": n} for n in kit.LABELS]),
            "repos/alice/shop/branches/main/protection":
                (200, {"required_status_checks": {"contexts": list(kit.REQUIRED_CHECKS)}}),
        }
        self.asked = []

        def fake(host, path):
            self.asked.append((host, path))
            return self.answers[path]
        fake.__wrapped__ = kit.gh_api
        patcher = mock.patch.object(kit, "gh_api", fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def install_bmad(self, initiative=None):
        (self.proj / "_bmad").mkdir(exist_ok=True)
        (self.proj / ".claude/skills/bmad-build").mkdir(parents=True)
        (self.proj / ".claude/skills/bmad-build/SKILL.md").write_text("bmad\n")
        if initiative:
            (self.proj / kit.BMAD_USER_CONFIG).write_text(f'[core]\nactive_initiative = "{initiative}"\n')

    def opens(self, *args):
        code, text = self.run_kit("doctor", *args)
        self.assertEqual(code, 0, text)
        return [line for line in text.splitlines() if line.startswith("open: ")]

    def test_a_complete_setup_has_nothing_open(self):
        self.install_bmad("initiative-shop")
        self.assertEqual(self.opens(), [])
        self.assertEqual(self.asked[0][0], "github.com")

    def test_actions_off_points_to_the_judge(self):
        self.install_bmad("initiative-shop")
        self.answers["repos/alice/shop/actions/permissions"] = (200, {"enabled": False})
        opens = self.opens()
        self.assertEqual(len(opens), 1, opens)
        self.assertIn("GitHub Actions is off", opens[0])
        self.assertIn("Without GitHub Actions", opens[0])

    def test_missing_labels_and_protection(self):
        self.install_bmad("initiative-shop")
        self.answers["repos/alice/shop/labels?per_page=100"] = (200, [{"name": "human-judge-change"}])
        self.answers["repos/alice/shop/branches/main/protection"] = (404, "Branch not protected")
        opens = " ".join(self.opens())
        self.assertIn("human-approved-irreversible, human-granted-round", opens)
        self.assertIn("`main` is not protected", opens)

    def test_protection_not_available_on_the_plan(self):
        self.install_bmad("initiative-shop")
        self.answers["repos/alice/shop/branches/main/protection"] = (403, "Upgrade to GitHub Pro")
        self.assertIn("not enforced", " ".join(self.opens()))

    def test_protection_without_the_three_checks(self):
        self.install_bmad("initiative-shop")
        self.answers["repos/alice/shop/branches/main/protection"] = (
            200, {"required_status_checks": {"contexts": [], "checks": [{"context": "gates"}]}})
        self.assertIn("does not require protected-paths, scope-guard", " ".join(self.opens()))

    def test_no_bmad_then_no_initiative(self):
        self.assertIn("BMAD is not installed", " ".join(self.opens()))
        self.install_bmad()
        opens = " ".join(self.opens())
        self.assertIn("No active BMAD initiative", opens)
        self.assertIn(kit.BMAD_USER_CONFIG, opens)
        (self.proj / kit.BMAD_USER_CONFIG).write_text('[core]\nactive_initiative = "initiative-shop"\n')
        self.assertEqual(self.opens(), [])

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlinked_skills_are_open(self):
        self.install_bmad("initiative-shop")
        (self.proj / ".agents/skills/bmad").mkdir(parents=True)
        os.symlink("../../.agents/skills/bmad", self.proj / ".claude/skills/bmad")
        self.assertIn("--copy", " ".join(self.opens()))

    def test_gh_that_cannot_ask_is_one_open_line(self):
        self.install_bmad("initiative-shop")
        for path in self.answers:
            self.answers[path] = (None, "gh is not installed")
        opens = self.opens()
        self.assertEqual(len(opens), 1, opens)
        self.assertIn("Could not ask GitHub (gh is not installed)", opens[0])

    def test_offline_asks_nothing(self):
        self.install_bmad("initiative-shop")
        self.assertEqual(self.opens("--offline"), [])
        self.assertEqual(self.asked, [])

    def test_origin_forms(self):
        for url, want in (("https://github.com/alice/shop.git", ("github.com", "alice", "shop")),
                          ("git@github.example.com:team/shop.git", ("github.example.com", "team", "shop")),
                          ("ssh://git@github.com/alice/shop", ("github.com", "alice", "shop"))):
            git(self.proj, "remote", "set-url", "origin", url)
            self.assertEqual(kit.github_repo(self.proj), want)

    @unittest.skipIf(os.name == "nt", "the stand-in gh is a shell script")
    def test_gh_api_reads_gh_answers(self):
        bindir = self.tmp / "fakebin"
        bindir.mkdir()
        (bindir / "gh").write_text(
            "#!/bin/sh\n"
            'case "$4" in\n'
            '  ok) echo \'{"enabled": false}\' ;;\n'
            '  missing) echo \'{"message":"Branch not protected","status":"404"}\'; '
            'echo "gh: Branch not protected (HTTP 404)" >&2; exit 1 ;;\n'
            '  *) echo "To get started with GitHub CLI, please run:  gh auth login" >&2; exit 4 ;;\n'
            "esac\n")
        (bindir / "gh").chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}):
            self.assertEqual(kit.gh_api.__wrapped__("github.com", "ok"), (200, {"enabled": False}))
            self.assertEqual(kit.gh_api.__wrapped__("github.com", "missing"), (404, "Branch not protected"))
            status, why = kit.gh_api.__wrapped__("github.com", "other")
            self.assertIsNone(status)
            self.assertIn("gh auth login", why)

    def test_sync_asks_github_nothing(self):
        self.run_kit("sync")
        self.assertEqual(self.asked, [])


class SmallTests(Base):
    def test_gitignore_lines_appended_once_never_removed(self):
        (self.proj / ".gitignore").write_text("mine/\n")
        commit_all(self.proj, "ignore", when=1_000_150)
        self.init()
        text = self.text(".gitignore")
        self.assertTrue(text.startswith("mine/\n"))
        self.assertIn(".lap/", text)
        (self.kit / "template/.gitignore").write_text((self.kit / "template/.gitignore").read_text() + "new-dir/\n")
        commit_all(self.kit, "ignore more", when=1_000_300)
        self.run_kit("sync")
        text = self.text(".gitignore")
        self.assertEqual(text.count(".lap/"), 1)
        self.assertEqual(text.count("new-dir/"), 1)
        self.assertIn("mine/", text)

    def test_crlf_and_lf_hash_the_same(self):
        self.assertEqual(kit.digest(b"a\r\nb\r\n"), kit.digest(b"a\nb\n"))
        self.assertNotEqual(kit.digest(b"a\nb\n"), kit.digest(b"a\nc\n"))

    def test_a_crlf_working_copy_is_not_a_change(self):
        self.init()
        p = self.proj / "RUNBOOK.md"
        lf = p.read_bytes().replace(b"\r\n", b"\n")
        flipped = lf if b"\r\n" in p.read_bytes() else lf.replace(b"\n", b"\r\n")  # the other line ending
        p.write_bytes(flipped)
        # .gitattributes pins the kit's files to LF; a project made before it may still hold CRLF.
        (self.proj / ".git/info").mkdir(exist_ok=True)
        (self.proj / ".git/info/attributes").write_text("RUNBOOK.md -text\n")
        commit_all(self.proj, "line endings", when=1_000_300)
        self.assertIn("i/crlf" if b"\r\n" in flipped else "i/lf", git(self.proj, "ls-files", "--eol", "RUNBOOK.md"))
        self.assertIn("nothing to do", self.run_kit("sync")[1])

    def test_sync_refuses_a_dirty_project_or_kit(self):
        self.init()
        (self.proj / "app.txt").write_text("edited\n")
        code, text = self.run_kit("sync")
        self.assertEqual(code, 2)
        self.assertIn("uncommitted", text)
        git(self.proj, "checkout", "--", "app.txt")
        (self.kit / "template/RUNBOOK.md").write_text("half done\n")
        code, text = self.run_kit("sync")
        self.assertEqual(code, 2)
        self.assertIn("kit clone", text)

    def test_sync_needs_the_kit_on_an_up_to_date_main(self):  # issue #44
        self.init()
        origin = self.tmp / "factory-kit-origin.git"
        git(self.tmp, "clone", "-q", "--bare", str(self.kit), str(origin))
        git(self.kit, "remote", "add", "origin", str(origin))
        git(self.kit, "fetch", "-q", "origin")
        git(self.kit, "switch", "-q", "-c", "factory/merged-already")
        code, text = self.run_kit("sync")
        self.assertEqual(code, 2)
        self.assertIn("on the branch `factory/merged-already`, not `main`", text)
        self.assertIn("git switch main", text)
        git(self.kit, "switch", "-q", "--detach")
        self.assertIn("not on a branch", self.run_kit("sync")[1])
        git(self.kit, "switch", "-q", "main")
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(origin), str(other))
        (other / "README.md").write_text("moved\n")
        commit_all(other, "move main", when=1_000_300)
        git(other, "push", "-q", "origin", "HEAD:main")
        code, text = self.run_kit("sync")
        self.assertEqual(code, 2)
        self.assertIn("`main` is 1 commit(s) behind origin/main", text)
        git(self.kit, "pull", "-q", "--ff-only", "origin", "main")
        code, text = self.run_kit("sync")
        self.assertEqual(code, 0, text)

    def test_sync_without_a_lock_asks_for_adopt(self):
        code, text = self.run_kit("sync")
        self.assertEqual(code, 2)
        self.assertIn("--adopt", text)


class AdoptTests(unittest.TestCase):
    """A project made before kit.py, from a kit whose files sat at the root and the fence in fence/."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.kit = self.tmp / "factory-kit"
        git(self.tmp, "init", "-q", "-b", "main", str(self.kit))
        git(self.kit, "config", "core.autocrlf", "false")
        # The old layout: factory files at the root, the fenced settings in fence/.
        for folder in ("harness", ".claude/skills", ".kiro/skills"):
            shutil.copytree(REAL / "template" / folder, self.kit / folder, ignore=shutil.ignore_patterns("__pycache__"))
        for rel in ("RUNBOOK.md", "MODIFYING.md", "AGENTS.md"):
            shutil.copy(REAL / "template" / rel, self.kit / rel)
        (self.kit / "fence").mkdir()
        shutil.copy(REAL / "template/.claude/settings.json", self.kit / "fence/claude-settings.json")
        shutil.copy(REAL / "template/.kiro/agents/factory.json", self.kit / "fence/kiro-factory.json")
        self.old = commit_all(self.kit, "old layout", when=1_000_000)
        # The project, made from the old kit: the same files, the fence in place.
        self.proj = self.tmp / "pilot"
        git(self.tmp, "init", "-q", "-b", "main", str(self.proj))
        git(self.proj, "config", "core.autocrlf", "false")
        for rel in ("harness", ".claude/skills", ".kiro/skills"):
            shutil.copytree(self.kit / rel, self.proj / rel)
        for rel in ("RUNBOOK.md", "MODIFYING.md", "AGENTS.md"):
            shutil.copy(self.kit / rel, self.proj / rel)
        (self.proj / "RUNBOOK.md").write_text((self.proj / "RUNBOOK.md").read_text() + "\npilot-only section\n")
        shutil.copy(self.kit / "fence/claude-settings.json", self.proj / ".claude/settings.json")
        (self.proj / ".kiro/agents").mkdir(parents=True)
        shutil.copy(self.kit / "fence/kiro-factory.json", self.proj / ".kiro/agents/factory.json")
        (self.proj / ".github").mkdir()
        (self.proj / ".github/CODEOWNERS").write_text("/harness/ @alice\n")
        commit_all(self.proj, "made from the old kit", when=1_000_100)
        # The migration: the same files moved into template/, the runbook rewritten, bin/ and seed/ added.
        (self.kit / "template").mkdir()
        git(self.kit, "mv", "harness", "template/harness")
        for rel in (".claude/skills", ".kiro/skills"):
            (self.kit / "template" / rel).parent.mkdir(parents=True, exist_ok=True)
            git(self.kit, "mv", rel, f"template/{rel}")
        for rel in ("RUNBOOK.md", "MODIFYING.md", "AGENTS.md"):
            git(self.kit, "mv", rel, f"template/{rel}")
        (self.kit / "template/.claude").mkdir(exist_ok=True)
        (self.kit / "template/.kiro/agents").mkdir(parents=True)
        git(self.kit, "mv", "fence/claude-settings.json", "template/.claude/settings.json")
        git(self.kit, "mv", "fence/kiro-factory.json", "template/.kiro/agents/factory.json")
        shutil.copytree(REAL / "seed", self.kit / "seed")
        shutil.copytree(REAL / "bin", self.kit / "bin", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(REAL / "template/.gitignore", self.kit / "template/.gitignore")
        (self.kit / "template/RUNBOOK.md").write_text("the kit's new runbook\n")
        commit_all(self.kit, "migration", when=1_000_200)

    def run_kit(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = kit.main(["--kit", str(self.kit), "--project", str(self.proj), *args])
        return code, buf.getvalue()

    def test_adopt_updates_what_the_migration_changed_and_nothing_else(self):
        code, text = self.run_kit("sync", "--adopt", self.old)
        self.assertEqual(code, 0, text)
        self.assertEqual((self.proj / "RUNBOOK.md").read_text(), "the kit's new runbook\n")
        self.assertIn("both changed RUNBOOK.md: the kit's change reached main later", text)
        changed = git(self.proj, "status", "--porcelain")
        self.assertIn("RUNBOOK.md", changed)
        self.assertIn("kit.lock.json", changed)
        self.assertIn(".gitignore", changed)
        self.assertNotIn("harness/", changed)
        self.assertNotIn("CODEOWNERS", changed)
        self.assertNotIn(".claude/settings.json", changed)

    def test_adopt_lock_hashes_come_from_the_old_revision(self):
        target = kit.Kit(self.kit)
        lock = kit.adopt_lock(target, self.old)
        self.assertEqual(lock["files"]["harness/judge/judge.py"],
                         kit.digest((self.kit / "template/harness/judge/judge.py").read_bytes()))
        self.assertEqual(lock["files"]["RUNBOOK.md"], kit.digest(git_show(self.kit, self.old, "RUNBOOK.md")))
        self.assertIn("Edit(/harness/**)", lock["fence"][".claude/settings.json"])


class MatureTests(Base):
    def setUp(self):
        super().setUp()
        self.init()
        (self.kit / "bin/kit.json").write_text(json.dumps({"phase": "mature"}))
        commit_all(self.kit, "the kit is mature", when=1_000_300)

    def test_a_project_change_stops_sync_and_fails_doctor_and_discard_restores(self):
        (self.proj / "RUNBOOK.md").write_text("mine\n")
        commit_all(self.proj, "project fix", when=1_000_400)
        code, text = self.run_kit("sync")
        self.assertEqual(code, 2)
        self.assertIn("open an issue", text.lower())
        self.assertEqual(git(self.proj, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertNotIn("factory/sync-", git(self.proj, "branch"))
        self.assertEqual(self.run_kit("doctor")[0], 1)
        code, text = self.run_kit("sync", "--discard", "RUNBOOK.md")
        self.assertEqual(code, 0, text)
        self.assertNotEqual(self.text("RUNBOOK.md"), "mine\n")


def git_show(cwd, rev, path):
    return subprocess.run(["git", "-C", str(cwd), "show", f"{rev}:{path}"], capture_output=True).stdout


def normal_text(s):
    return s.replace("\r\n", "\n")


if __name__ == "__main__":
    unittest.main()
