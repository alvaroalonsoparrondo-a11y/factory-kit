"""Tests of the dispatcher with Git, GitHub and the agent processes faked. Human-owned.

Run: python -m unittest discover -s harness/dispatch -v
"""
import copy
import os
import tempfile
import unittest
from pathlib import Path

import dispatch as d

EPIC = "epic-shortlink"
SOURCE = f"_bmad-output/init/tickets/{EPIC}/tickets/tickets.toml"
MAIN = "m" * 40
GREEN = {c: "green" for c in d.board.CHECKS}
NOW = 1_800_000_000.0


def ticket(id, after=(), touches=None, post_merge=(), hitl=False, title="A ticket"):
    return {"epic": EPIC, "id": str(id), "ref": f"1.{id}", "title": title, "after": [str(a) for a in after],
            "hitl": hitl, "risk": "", "source": SOURCE, "touches": touches, "post_merge": list(post_merge)}


def plan(id, status, blocked=""):
    return {"path": f"_bmad-output/init/tickets/{EPIC}/tickets/story-{id}-plan.md", "epic": EPIC, "ticket": str(id),
            "status": status, "review": "", "review_loop_iteration": "0",
            "blocked_at": "2026-11-18" if blocked else "", "blocked_reason": blocked}


def pull(number, branch, state="open", merged=False, checks=None, holdouts=""):
    states = {c: {"state": s, "description": holdouts if c == "holdouts" else ""} for c, s in (checks or {}).items()}
    return {"number": number, "url": f"https://github.com/o/r/pull/{number}", "branch": branch, "state": state,
            "merged": merged, "checks": states, "judged_commits": 1, "human_reviews": 0}


def snap(tickets):
    return {"repo": "o/r", "server": "https://github.com", "main_sha": MAIN[:7], "tickets": tickets,
            "plans": {"main": []}, "branches": [], "pulls": [], "problems": [], "now": NOW}


class FakeRepo:
    root = "."

    def __init__(self):
        self.heads = {"origin/main": MAIN}
        self.behind = set()
        self.main_files = set()
        self.main_branch, self.main_dirty = "main", False
        self.calls = []

    def fetch(self):
        self.calls.append(("fetch",))

    def sha(self, ref):
        return self.heads.get(ref)

    def contains(self, ancestor, ref):
        return ref.removeprefix("origin/") not in self.behind

    def file_on_main(self, path):
        return path in self.main_files

    def main_checkout(self):
        return Path("/work/factory-pilot")

    def main_checkout_state(self):
        return self.main_branch, self.main_dirty

    def pull_main_checkout(self):
        self.calls.append(("pull",))

    def add_worktree(self, path, branch):
        self.calls.append(("worktree add", branch))

    def remove_worktree(self, path, branch):
        self.calls.append(("worktree remove", branch))

    def mark_done(self, ticket, ref, pr):
        self.calls.append(("mark done", ref, pr))


class FakeGitHub:
    repo = "o/r"

    def __init__(self, taken=()):
        self.taken = set(taken)
        self.created = []

    def create_ref(self, branch, sha):
        if branch in self.taken:
            return False
        self.taken.add(branch)
        self.created.append((branch, sha))
        return True

    def failing_summary(self, sha, check):
        return "failed: H-03" if check == "holdouts" else "GATE FAIL: e2e journey 01 timed out"


class FakeRunner:
    def __init__(self):
        self.started, self.live, self.exits, self.logs = [], set(), {}, {}
        self.next_pid = 100

    def start(self, argv, cwd, env, log, exit_file):
        self.next_pid += 1
        self.started.append({"argv": argv, "cwd": cwd, "env": env, "log": str(log), "pid": self.next_pid})
        self.live.add(self.next_pid)
        return self.next_pid

    def alive(self, pid):
        return pid in self.live

    def exit_code(self, exit_file):
        return self.exits.get(str(exit_file))

    def log_tail(self, log, chars=4000):
        return self.logs.get(str(log), "")

    def finish(self, run, code=0, log=""):
        self.live.discard(run["pid"])
        self.exits[run["exit_file"]] = code
        self.logs[run["log"]] = log


class MemStore(d.Store):
    def __init__(self):
        super().__init__("/work/factory-pilot/.factory")
        self.state, self.lines, self.pause = {"runs": {}}, [], False

    def load(self):
        return copy.deepcopy(self.state)

    def save(self, state):
        self.state = copy.deepcopy(state)

    def report(self, line):
        self.lines.append(line)

    def paused(self):
        return self.pause


class World:
    def __init__(self, tickets, shared=(), cap=2, taken=(), agents=True, deny=("Edit(/harness/**)",),
                 allow_no_fence=False):
        self.snapshot = snap(tickets)
        self.repo, self.gh, self.runner, self.store = FakeRepo(), FakeGitHub(taken), FakeRunner(), MemStore()
        self.now = NOW
        files = {SOURCE: "shared = [" + ", ".join(f'"{s}"' for s in shared) + "]\n"}
        self.make = lambda dry=False: d.Dispatcher(
            self.repo, self.gh, self.runner, self.store, cap=cap, dry_run=dry, agents=agents,
            allow_no_fence=allow_no_fence, collect_fn=lambda: (copy.deepcopy(self.snapshot), files),
            fence=lambda: list(deny), worktree_root="/work/wt", clock=lambda: self.now)

    def tick(self, dry=False):
        self.snapshot["now"] = self.now
        return self.make(dry).tick()

    def run(self, ref):
        return self.store.state["runs"][ref]

    def merged(self, *ids):
        """Tickets merged earlier, outside this dispatcher."""
        self.snapshot["pulls"] += [pull(90 + int(i), f"story/1.{i}", "closed", merged=True, checks=GREEN) for i in ids]

    def on_branch(self, ref, sha=None, checks=None, holdouts="", **pr):
        branch = f"story/{ref}"
        if branch not in self.snapshot["branches"]:
            self.snapshot["branches"].append(branch)
        if sha:
            self.repo.heads[f"origin/{branch}"] = sha
        if checks is not None:
            self.snapshot["pulls"] = [p for p in self.snapshot["pulls"] if p["branch"] != branch]
            self.snapshot["pulls"].append(pull(5, branch, checks=checks, holdouts=holdouts, **pr))


def refs(items):
    return [i[0] if isinstance(i, tuple) else i for i in items]


class ReadySet(unittest.TestCase):
    def test_first_ticket_is_claimed_and_started(self):
        w = World([ticket(1, touches=["backend/**"]), ticket(2, after=[1])])
        rep = w.tick()
        self.assertEqual(rep["ready"], ["1.1"])
        self.assertEqual(w.gh.created, [("story/1.1", MAIN)])
        self.assertIn(("worktree add", "story/1.1"), w.repo.calls)
        started = w.runner.started[0]
        self.assertEqual(Path(started["cwd"]), Path("/work/wt/story-1.1"))
        self.assertEqual(started["env"]["PORT"], "8091")
        self.assertTrue(started["argv"][2].startswith("lap 1.1"))
        self.assertIn("--session-id", started["argv"])
        self.assertIn(("1.2", "after 1.1"), rep["waiting"])

    def test_after_must_be_merged(self):
        w = World([ticket(1), ticket(2, after=[1])])
        w.on_branch("1.1")
        w.snapshot["plans"]["story/1.1"] = [plan(1, "built")]
        rep = w.tick()
        self.assertEqual(rep["ready"], [])
        self.assertIn("hand-started lap", dict(rep["needs_you"])["1.1"])

    def test_parallel_tickets_with_separate_touches_both_start(self):
        w = World([ticket(1), ticket(2, after=[1], touches=["backend/a/**"]),
                   ticket(3, after=[1], touches=["frontend/**"])])
        w.merged(1)
        rep = w.tick()
        self.assertEqual(rep["ready"], ["1.2", "1.3"])
        self.assertEqual([s["env"]["PORT"] for s in w.runner.started], ["8091", "8092"])

    def test_overlapping_touches_wait(self):
        w = World([ticket(1), ticket(2, after=[1], touches=["backend/src/**"]),
                   ticket(3, after=[1], touches=["backend/src/main/Links.java"])])
        w.merged(1)
        rep = w.tick()
        self.assertEqual(refs(rep["claimed"]), ["1.2"])
        self.assertIn(("1.3", "ready, but its files overlap 1.2"), rep["waiting"])

    def test_shared_files_do_not_clash(self):
        w = World([ticket(1), ticket(2, after=[1], touches=["docs/openapi.yaml", "backend/a/**"]),
                   ticket(3, after=[1], touches=["docs/openapi.yaml", "backend/b/**"])], shared=["docs/openapi.yaml"])
        w.merged(1)
        self.assertEqual(refs(w.tick()["claimed"]), ["1.2", "1.3"])

    def test_a_ticket_without_touches_runs_alone(self):
        w = World([ticket(1), ticket(2, after=[1]), ticket(3, after=[1], touches=["frontend/**"])])
        w.merged(1)
        rep = w.tick()
        self.assertEqual(refs(rep["claimed"]), ["1.2"])
        self.assertIn("1.3", refs(rep["waiting"]))

    def test_the_cap(self):
        w = World([ticket(i, touches=[f"part{i}/**"]) for i in (1, 2, 3)], cap=2)
        rep = w.tick()
        self.assertEqual(refs(rep["claimed"]), ["1.1", "1.2"])
        self.assertIn("1.3", refs(rep["waiting"]))

    def test_hitl_is_left_to_the_human(self):
        w = World([ticket(1, hitl=True)])
        rep = w.tick()
        self.assertEqual(w.gh.created, [])
        self.assertIn("1.1", refs(rep["needs_you"]))

    def test_blocked_ticket_is_not_started(self):
        w = World([ticket(1)])
        w.snapshot["plans"]["main"] = [plan(1, "draft", blocked="FACTORY_RULES 1")]
        self.assertEqual(w.tick()["claimed"], [])

    def test_dry_run_claims_and_writes_nothing(self):
        w = World([ticket(1)])
        rep = w.tick(dry=True)
        self.assertEqual(rep["claimed"], [("1.1", "would claim story/1.1 and start `lap 1.1` on port 8091")])
        self.assertEqual((w.gh.created, w.runner.started, w.repo.calls), ([], [], []))
        self.assertEqual(w.store.state, {"runs": {}})

    def test_paused_starts_nothing(self):
        w = World([ticket(1)])
        w.store.pause = True
        rep = w.tick()
        self.assertEqual((w.gh.created, rep["claimed"]), ([], []))
        self.assertIn("paused", dict(rep["waiting"])["1.1"])


class Fence(unittest.TestCase):
    def test_fence_off_starts_no_headless_lap(self):
        w = World([ticket(1)], deny=())
        rep = w.tick()
        self.assertEqual((w.gh.created, w.runner.started), ([], []))
        self.assertIn("The fence is off", rep["problems"][0])

    def test_fence_off_allowed_on_request(self):
        w = World([ticket(1)], deny=(), allow_no_fence=True)
        self.assertEqual(refs(w.tick()["claimed"]), ["1.1"])

    def test_fence_off_does_not_stop_human_run_laps(self):
        w = World([ticket(1)], deny=(), agents=False)
        self.assertEqual(refs(w.tick()["claimed"]), ["1.1"])

    def test_headless_command_keeps_the_fence(self):
        argv = d.claude_argv("lap 1.1", "s")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("bypassPermissions", argv)

    def test_token_is_never_passed_to_the_agent(self):
        os.environ["FACTORY_DISPATCH_TOKEN"] = os.environ["GH_TOKEN"] = "secret"
        try:
            env = d.agent_env(8091, "1.1")
            for name in ("FACTORY_DISPATCH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
                self.assertNotIn(name, env)
        finally:
            del os.environ["FACTORY_DISPATCH_TOKEN"], os.environ["GH_TOKEN"]


class Claim(unittest.TestCase):
    def test_a_taken_branch_is_skipped(self):
        w = World([ticket(1, touches=["a/**"]), ticket(2, touches=["b/**"])], taken=["story/1.1"])
        rep = w.tick()
        self.assertEqual(refs(rep["claimed"]), ["1.2"])
        self.assertIn("someone else took it", rep["problems"][0])
        self.assertNotIn("1.1", w.store.state["runs"])
        self.assertEqual(len(w.runner.started), 1)


class Routing(unittest.TestCase):
    def started_lap(self, **kw):
        w = World([ticket(1, title="Skeleton"), ticket(2, after=[1])], **kw)
        w.tick()
        w.on_branch("1.1")
        return w

    def pushed(self, w, sha="b1", checks=None, holdouts="", code=0, log=""):
        w.runner.finish(w.run("1.1"), code, log)
        w.on_branch("1.1", sha, checks, holdouts)

    def test_running_lap_is_left_alone(self):
        w = self.started_lap()
        rep = w.tick()
        self.assertEqual(refs(rep["running"]), ["1.1"])
        self.assertEqual(len(w.runner.started), 1)

    def test_a_quiet_running_lap_goes_to_the_human(self):
        w = self.started_lap()
        w.snapshot["activity"] = {"idle_seconds": {"story/1.1": 4000}, "quiet_seconds": 3600}
        self.assertIn("quiet for 66 min", dict(w.tick()["needs_you"])["1.1"])

    def test_pushed_without_pull_request_asks_for_one(self):
        w = self.started_lap()
        self.pushed(w)
        self.assertIn("could not open its pull request", dict(w.tick()["needs_you"])["1.1"])

    def test_red_gates_start_a_fix_round_with_the_failure(self):
        w = self.started_lap()
        self.pushed(w, checks={**GREEN, "gates": "red"})
        rep = w.tick()
        self.assertEqual(refs(rep["started"]), ["1.1"])
        prompt = w.runner.started[-1]["argv"][2]
        self.assertTrue(prompt.startswith("lap 1.1 fix round"))
        self.assertIn("Check `gates` failed on b1", prompt)
        self.assertIn("GATE FAIL: e2e journey 01 timed out", prompt)
        self.assertEqual(w.run("1.1")["fix_rounds"], 1)

    @unittest.skipUnless("holdouts" in d.board.CHECKS, "this project has no holdouts check")
    def test_red_holdouts_pass_only_the_id(self):
        w = self.started_lap()
        self.pushed(w, checks={**GREEN, "holdouts": "red"}, holdouts="failed: H-03")
        w.tick()
        self.assertIn("failed: H-03", w.runner.started[-1]["argv"][2])
        self.assertEqual(w.run("1.1")["failed_checks"], ["holdouts H-03"])

    def test_a_red_guard_goes_to_the_human(self):
        w = self.started_lap()
        self.pushed(w, checks={**GREEN, "scope-guard": "red"})
        rep = w.tick()
        self.assertEqual(len(w.runner.started), 1)
        self.assertIn(("1.1", "Review the change: label it or send it back (scope-guard)"), rep["needs_you"])

    def test_fix_round_that_pushes_nothing_stops_until_released(self):
        w = self.started_lap()
        self.pushed(w, checks={**GREEN, "gates": "red"})
        w.tick()
        w.runner.finish(w.run("1.1"))
        self.assertIn("pushed nothing new", dict(w.tick()["needs_you"])["1.1"])
        self.assertIn("dispatch.py release 1.1", dict(w.tick()["needs_you"])["1.1"])
        self.assertEqual(len(w.runner.started), 2)

    def test_more_than_three_fix_rounds_stop(self):
        w = self.started_lap()
        for n in range(1, 5):
            self.pushed(w, sha=f"b{n}", checks={**GREEN, "gates": "red"})
            rep = w.tick()
        self.assertEqual(w.run("1.1")["fix_rounds"], 3)
        self.assertIn("round budget spent, still red (gates): 3 of 3 rounds used", dict(rep["needs_you"])["1.1"])
        self.assertEqual(len(w.runner.started), 4)

    def rounds(self, w, *sources, grants=0):
        events = [{"at": "2027-01-15T08:00:00+00:00", "state": "round", "source": s, "text": f"finding {n}", "n": n}
                  for n, s in enumerate(sources, 1)]
        events += [{"at": "2027-01-15T09:00:00+00:00", "state": "grant", "n": grants, "text": "ok"}] if grants else []
        w.snapshot["signals"] = {"1.1": events}

    def test_the_laps_own_rounds_share_the_budget(self):
        w = self.started_lap()
        self.rounds(w, "review", "gates")  # two rounds before CI saw the pull request
        self.pushed(w, sha="b1", checks={**GREEN, "gates": "red"})
        w.tick()
        self.assertEqual(w.run("1.1")["fix_rounds"], 1)  # the third and last round
        self.rounds(w, "review", "gates", "ci")
        self.pushed(w, sha="b2", checks={**GREEN, "gates": "red"})
        rep = w.tick()
        self.assertIn("3 of 3 rounds used (review 1, gates 1, ci 1)", dict(rep["needs_you"])["1.1"])
        self.assertEqual(len(w.runner.started), 2)

    def test_deleting_the_laps_record_does_not_buy_rounds(self):
        w = self.started_lap()
        for n in range(1, 4):
            self.pushed(w, sha=f"b{n}", checks={**GREEN, "gates": "red"})
            w.tick()
        w.snapshot["signals"] = {}
        self.pushed(w, sha="b4", checks={**GREEN, "gates": "red"})
        self.assertIn("round budget spent", dict(w.tick()["needs_you"])["1.1"])

    def test_a_human_grant_gives_one_more_round(self):
        w = self.started_lap()
        self.rounds(w, "review", "gates", "ci", grants=1)
        self.pushed(w, sha="b1", checks={**GREEN, "gates": "red"})
        rep = w.tick()
        self.assertEqual(refs(rep["started"]), ["1.1"])
        self.assertTrue(w.runner.started[-1]["argv"][2].startswith("lap 1.1 fix round"))

    def test_more_than_three_main_moved_rounds_stop(self):
        w = self.started_lap()
        w.repo.behind.add("story/1.1")
        for n in range(1, 5):
            self.pushed(w, sha=f"m{n}", checks=GREEN)
            rep = w.tick()
        self.assertEqual(w.run("1.1")["moved_rounds"], 3)
        self.assertIn("still behind main after 3 main-moved rounds", dict(rep["needs_you"])["1.1"])

    def test_behind_main_starts_a_main_moved_round(self):
        w = self.started_lap()
        self.pushed(w, checks=GREEN)
        w.repo.behind.add("story/1.1")
        rep = w.tick()
        self.assertEqual(refs(rep["started"]), ["1.1"])
        self.assertTrue(w.runner.started[-1]["argv"][2].startswith("lap 1.1 main moved"))

    def test_green_and_current_asks_for_review(self):
        w = self.started_lap()
        self.pushed(w, checks=GREEN)
        self.assertIn(("1.1", "Review and merge"), w.tick()["needs_you"])

    def test_checks_running_waits(self):
        w = self.started_lap()
        self.pushed(w, checks={**GREEN, "gates": "running"})
        self.assertIn(("1.1", "CI is running"), w.tick()["waiting"])

    def test_a_stopped_lap_is_not_retried(self):
        w = self.started_lap()
        w.runner.finish(w.run("1.1"), code=1)
        self.assertIn("stopped (exit 1)", dict(w.tick()["needs_you"])["1.1"])
        self.assertEqual(len(w.runner.started), 1)

    def test_a_lap_that_pushed_nothing_stops(self):
        w = self.started_lap()
        self.pushed(w, sha=MAIN)
        self.assertIn("without pushing any work", dict(w.tick()["needs_you"])["1.1"])

    def test_a_blocked_lap_stops(self):
        w = self.started_lap()
        self.pushed(w)
        w.snapshot["plans"]["story/1.1"] = [plan(1, "draft", blocked="FACTORY_RULES 1: migration")]
        self.assertEqual(dict(w.tick()["needs_you"])["1.1"], "blocked: FACTORY_RULES 1: migration.")

    def test_a_lap_that_signals_a_wait_shows_how_to_answer(self):
        w = self.started_lap()
        self.pushed(w)
        w.snapshot["signals"] = {"1.1": [{"at": "2027-01-15T08:00:00+00:00", "state": "waiting",
                                          "kind": "approval", "text": "Approve the plan"}]}
        why = dict(w.tick()["needs_you"])["1.1"]
        self.assertIn("Approve the plan", why)
        self.assertIn(f"claude --resume {w.run('1.1')['session']}", why)

    def test_release_lets_a_stopped_lap_be_routed_again(self):
        w = self.started_lap()
        w.runner.finish(w.run("1.1"), code=1)
        w.tick()
        w.store.state["runs"]["1.1"].update(halted=None, handled_sha=None, retry_after=None, released=True)  # `release`
        w.on_branch("1.1", "b9", checks=GREEN)
        self.assertIn(("1.1", "Review and merge"), w.tick()["needs_you"])


class UsageLimits(unittest.TestCase):
    def test_a_usage_limit_resumes_the_same_session_later(self):
        w = World([ticket(1)])
        w.tick()
        run = w.run("1.1")
        w.on_branch("1.1", MAIN)
        w.runner.finish(run, code=1, log="Claude AI usage limit reached|1800003600")
        rep = w.tick()
        self.assertIn("usage limit", dict(rep["waiting"])["1.1"])
        self.assertNotIn("1.1", refs(rep["needs_you"]))
        self.assertIn("resumes at", dict(w.tick()["waiting"])["1.1"])
        w.now += d.LIMIT_RETRY_MINUTES * 60 + 1
        rep = w.tick()
        self.assertEqual(refs(rep["started"]), ["1.1"])
        argv = w.runner.started[-1]["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], run["session"])
        self.assertEqual(w.run("1.1")["limit_retries"], 1)


class NoAgents(unittest.TestCase):
    def world(self):
        w = World([ticket(1), ticket(2, after=[1])], agents=False)
        rep = w.tick()
        w.on_branch("1.1", MAIN)
        return w, rep

    def test_claims_and_tells_the_human_to_start(self):
        w, rep = self.world()
        self.assertEqual(w.runner.started, [])
        self.assertIn(("worktree add", "story/1.1"), w.repo.calls)
        self.assertIn("say `lap 1.1`", dict(rep["needs_you"])["1.1"])
        self.assertIn("say `lap 1.1`", dict(w.tick()["needs_you"])["1.1"])

    def test_red_check_asks_for_a_fix_round_and_counts_it_once(self):
        w, _ = self.world()
        w.on_branch("1.1", "b1", checks={**GREEN, "gates": "red"})
        self.assertIn("`lap 1.1 fix round`", dict(w.tick()["needs_you"])["1.1"])
        w.tick()
        self.assertEqual(w.run("1.1")["fix_rounds"], 1)
        self.assertEqual(w.runner.started, [])

    def test_behind_main_asks_for_a_main_moved_round(self):
        w, _ = self.world()
        w.on_branch("1.1", "b1", checks=GREEN)
        w.repo.behind.add("story/1.1")
        self.assertIn("`lap 1.1 main moved`", dict(w.tick()["needs_you"])["1.1"])


class Closing(unittest.TestCase):
    def merged_lap(self):
        w = World([ticket(1, title="Skeleton"), ticket(2, after=[1])])
        w.tick()
        w.runner.finish(w.run("1.1"))
        w.on_branch("1.1", "b2", checks={**GREEN, "gates": "red"})
        w.tick()  # fix round 1
        w.runner.finish(w.run("1.1"))
        w.snapshot["pulls"] = [pull(5, "story/1.1", "closed", merged=True, checks=GREEN)]
        return w

    def test_close_marks_done_reports_and_cleans_up(self):
        w = self.merged_lap()
        rep = w.tick()
        self.assertEqual(refs(rep["closed"]), ["1.1"])
        self.assertIn(("mark done", "1.1", "PR #5"), w.repo.calls)
        self.assertIn(("pull",), w.repo.calls)
        self.assertIn(("worktree remove", "story/1.1"), w.repo.calls)
        self.assertIn("1.1 Skeleton | PR #5 | mode: agent | fix rounds: 1 | failed checks: gates", w.store.lines[0])
        self.assertNotIn("1.1", w.store.state["runs"])
        self.assertEqual(refs(rep["claimed"]), ["1.2"])

    def test_a_ticket_already_marked_done_is_not_marked_again(self):
        w = self.merged_lap()
        w.snapshot["plans"]["main"] = [plan(1, "done")]
        w.tick()
        self.assertFalse(any(c[0] == "mark done" for c in w.repo.calls))

    def test_a_main_checkout_off_main_is_left_alone(self):
        w = self.merged_lap()
        w.repo.main_branch = "story/9.9"
        rep = w.tick()
        self.assertNotIn(("pull",), w.repo.calls)
        self.assertIn("left alone", rep["problems"][0])

    def test_dry_run_close_changes_nothing(self):
        w = self.merged_lap()
        rep = w.tick(dry=True)
        self.assertIn("would close", rep["closed"][0][1])
        self.assertIn("1.1", w.store.state["runs"])
        self.assertEqual(w.store.lines, [])


class PostMerge(unittest.TestCase):
    LOCK = {"what": "commit empty harness/skeleton.lock", "done_when": "file:harness/skeleton.lock"}

    def test_unmet_action_is_listed_and_blocks_dependents(self):
        w = World([ticket(1, post_merge=[self.LOCK]), ticket(2, after=[1]), ticket(3, touches=["x/**"])])
        w.merged(1)
        rep = w.tick()
        self.assertIn(("1.1", "after the merge: commit empty harness/skeleton.lock"), rep["needs_you"])
        self.assertEqual(rep["post_merge_blocked"], [("1.2", "waits for the post-merge actions of 1.1")])
        self.assertEqual(refs(rep["claimed"]), ["1.3"])

    def test_met_action_unblocks(self):
        w = World([ticket(1, post_merge=[self.LOCK]), ticket(2, after=[1])])
        w.merged(1)
        w.repo.main_files.add("harness/skeleton.lock")
        rep = w.tick()
        self.assertEqual((rep["post_merge_blocked"], refs(rep["claimed"])), ([], ["1.2"]))

    def test_unknown_check_is_a_problem_and_stays_unmet(self):
        w = World([ticket(1, post_merge=[{"what": "x", "done_when": "label:foo"}]), ticket(2, after=[1])])
        w.merged(1)
        rep = w.tick()
        self.assertIn("unknown done_when", rep["problems"][0])
        self.assertEqual(refs(rep["post_merge_blocked"]), ["1.2"])


class Overlap(unittest.TestCase):
    def test_patterns(self):
        self.assertTrue(d.patterns_overlap("backend/**", "backend/src/A.java"))
        self.assertTrue(d.patterns_overlap("backend/src/**", "backend/**"))
        self.assertTrue(d.patterns_overlap("frontend/src/app/*.ts", "frontend/src/app/app.ts"))
        self.assertFalse(d.patterns_overlap("backend/**", "frontend/**"))
        self.assertFalse(d.patterns_overlap("docs/a.md", "docs/b.md"))
        self.assertTrue(d.touches_overlap(None, ["a"], set()))


class StoreFiles(unittest.TestCase):
    def test_state_pause_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = d.Store(Path(tmp) / ".factory")
            self.assertEqual(s.load(), {"runs": {}})
            s.save({"runs": {"1.1": {"port": 8091}}})
            s.report("a line")
            self.assertEqual(s.load()["runs"]["1.1"]["port"], 8091)
            self.assertEqual((Path(tmp) / ".factory" / ".gitignore").read_text(encoding="utf-8").splitlines()[-1], "*")
            self.assertEqual((Path(tmp) / ".factory" / "lap-reports.log").read_text(encoding="utf-8"), "a line\n")
            self.assertFalse(s.paused())
            s.set_paused(True)
            self.assertTrue(s.paused())
            s.set_paused(False)
            self.assertFalse(s.paused())
            with s.single_flight() as first:
                with s.single_flight() as second:
                    self.assertEqual((first, second), (True, False))
            with s.single_flight() as again:
                self.assertTrue(again)


if __name__ == "__main__":
    unittest.main()
