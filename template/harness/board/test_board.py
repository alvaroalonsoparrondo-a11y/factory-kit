"""Tests of the board's derivation and rendering. Human-owned.

Run: python3 -m unittest discover -s harness/board -v
"""
import unittest

import board as b

EPIC = "epic-shortlink"
EPIC_PATH = f"_bmad-output/init/tickets/{EPIC}/tickets"


def ticket(id, title="A ticket", after=(), hitl=False, epic=EPIC):
    return {"epic": epic, "id": str(id), "title": title, "after": [str(a) for a in after], "hitl": hitl, "risk": ""}


def plan(id, status, epic=EPIC, review="", loops=0, blocked=""):
    return {"path": f"_bmad-output/init/tickets/{epic}/tickets/story-{id}-plan.md", "epic": epic, "ticket": str(id),
            "status": status, "review": review, "review_loop_iteration": str(loops),
            "blocked_at": "2026-11-16" if blocked else "", "blocked_reason": blocked}


def pull(number, branch, state="open", merged=False, checks=None, judged=1, human=0):
    states = {c: {"state": s, "description": ""} for c, s in (checks or {}).items()}
    return {"number": number, "url": f"https://github.com/o/r/pull/{number}", "branch": branch, "state": state,
            "merged": merged, "checks": states, "judged_commits": judged, "human_reviews": human}


def snap(tickets, plans=None, branches=(), pulls=()):
    return {"repo": "o/r", "server": "https://github.com", "main_sha": "abc1234", "tickets": tickets,
            "plans": plans or {"main": []}, "branches": list(branches), "pulls": list(pulls), "problems": []}


def row(board, id, epic=EPIC):
    for e in board["epics"]:
        for r in e["rows"]:
            if r["epic"] == epic and r["id"] == str(id):
                return r
    raise AssertionError(f"no row {epic} #{id}")


GREEN = {c: "green" for c in b.CHECKS}


class Stages(unittest.TestCase):
    def test_backlog_only(self):
        board = b.derive(snap([ticket(1), ticket(2, after=[1]), ticket(3)]))
        self.assertEqual((row(board, 1)["stage"], row(board, 1)["status"]), ("Planned", "needs you"))
        self.assertEqual(row(board, 1)["needs_you"], "Start the lap")
        self.assertEqual((row(board, 2)["status"], row(board, 2)["waiting_on"]), ("waiting", ["1"]))
        self.assertEqual(row(board, 3)["status"], "ready")  # startable, but #1 is first in line
        self.assertIsNone(row(board, 1)["reviews"])

    def test_hitl_is_named(self):
        board = b.derive(snap([ticket(1, hitl=True)]))
        self.assertEqual(row(board, 1)["needs_you"], "Start the lap (human in the loop)")

    def test_branch_without_plan_is_lap_started(self):
        r = row(b.derive(snap([ticket(1)], branches=["story/1"])), 1)
        self.assertEqual((r["stage"], r["status"], r["needs_you"]), ("Lap started", "running", None))

    def test_plan_status_on_the_branch_sets_the_stage(self):
        for status, stage in (("draft", "Lap started"), ("ready-for-dev", "Lap started"),
                              ("in-progress", "Building"), ("in-review", "In review")):
            s = snap([ticket(1)], {"main": [], "story/1": [plan(1, status)]}, ["story/1"])
            self.assertEqual(row(b.derive(s), 1)["stage"], stage, status)

    def test_built_without_pull_request_is_running_while_active(self):
        # An active branch in "built" stage means the lap is running gates or runtime
        # verification — it should not prompt "Open the pull request" yet.
        s = snap([ticket(1)], {"main": [], "story/1": [plan(1, "built")]}, ["story/1"])
        r = row(b.derive(s), 1)
        self.assertEqual((r["stage"], r["status"], r["needs_you"]), ("Built", "running", None))

    def test_built_without_pull_request_asks_for_one_when_quiet(self):
        # Once the branch goes quiet (lap has stalled), prompt the human to open the PR.
        s = snap([ticket(1)], {"main": [], "story/1": [plan(1, "built")]}, ["story/1"])
        s["activity"] = {"idle_seconds": {"story/1": 700}, "quiet_seconds": 600}
        r = row(b.derive(s), 1)
        self.assertEqual(r["stage"], "Built")
        self.assertEqual(r["needs_you"], "[Open the pull request](https://github.com/o/r/compare/main...story/1?expand=1)")

    def test_merged_is_done_and_unlocks_the_next_ticket(self):
        s = snap([ticket(1), ticket(2, after=[1])], {"main": [plan(1, "built")]},
                 pulls=[pull(4, "story/1", "closed", merged=True, checks=GREEN)])  # branch deleted after merge
        board = b.derive(s)
        self.assertEqual((row(board, 1)["stage"], row(board, 1)["status"]), ("Done", "done"))
        self.assertEqual(row(board, 2)["needs_you"], "Start the lap")

    def test_plan_done_on_main_is_done_without_a_pull_request(self):
        self.assertEqual(row(b.derive(snap([ticket(1)], {"main": [plan(1, "done")]})), 1)["stage"], "Done")

    def test_dropped(self):
        r = row(b.derive(snap([ticket(1)], {"main": [plan(1, "dropped")]})), 1)
        self.assertEqual((r["stage"], r["status"], r["needs_you"]), ("Dropped", "dropped", None))

    def test_a_dropped_prerequisite_still_blocks(self):
        board = b.derive(snap([ticket(1), ticket(2, after=[1])], {"main": [plan(1, "dropped")]}))
        self.assertEqual(row(board, 2)["status"], "waiting")


class NeedsYou(unittest.TestCase):
    def in_ci(self, checks, **kw):
        s = snap([ticket(1)], {"main": [], "story/1": [plan(1, "built")]}, ["story/1"],
                 [pull(7, "story/1", checks=checks, **kw)])
        return row(b.derive(s), 1)

    def test_checks_running(self):
        r = self.in_ci({"gates": "running", "protected-paths": "green", "scope-guard": "green"})
        self.assertEqual((r["stage"], r["status"], r["needs_you"]), ("In CI", "running", None))

    def test_gates_red(self):
        r = self.in_ci({**GREEN, "gates": "red"})
        self.assertEqual((r["status"], r["needs_you"]), ("needs you", "Paste the failing check into the lap (gates)"))

    def test_a_red_guard_comes_before_a_red_gate(self):
        r = self.in_ci({**GREEN, "gates": "red", "scope-guard": "red"})
        self.assertEqual(r["needs_you"], "Review the change: label it or send it back (scope-guard)")

    def test_all_green(self):
        self.assertEqual(self.in_ci(GREEN)["needs_you"], "Review and merge")

    def test_a_check_that_never_reported(self):
        r = self.in_ci({"gates": "green", "protected-paths": "green"})
        self.assertEqual(r["needs_you"], "A required check has not reported: scope-guard")

    def test_closed_without_merge(self):
        s = snap([ticket(1)], branches=["story/1"], pulls=[pull(7, "story/1", "closed")])
        r = row(b.derive(s), 1)
        self.assertEqual((r["stage"], r["status"]), ("PR closed", "needs you"))

    def test_blocked_lap_shows_the_reason(self):
        s = snap([ticket(1)], {"main": [], "story/1": [plan(1, "draft", blocked="FACTORY_RULES 1: migration")]}, ["story/1"])
        r = row(b.derive(s), 1)
        self.assertEqual((r["status"], r["needs_you"]), ("blocked", "Decide: FACTORY_RULES 1: migration"))

    def test_a_merged_pull_request_wins_over_an_older_closed_one(self):
        s = snap([ticket(1)], pulls=[pull(9, "story/1", "closed", merged=True), pull(7, "story/1", "closed")])
        r = row(b.derive(s), 1)
        self.assertEqual((r["stage"], r["pr"]["number"]), ("Done", 9))


class Reviews(unittest.TestCase):
    def test_three_counts(self):
        s = snap([ticket(1)], {"main": [], "story/1": [plan(1, "built", review="thorough", loops=1)]}, ["story/1"],
                 [pull(7, "story/1", checks=GREEN, judged=3, human=1)])
        self.assertEqual(row(b.derive(s), 1)["reviews"], {"bmad": 2, "fix_rounds": 2, "human": 1, "findings": None})

    def test_no_review_yet(self):
        s = snap([ticket(1)], {"main": [], "story/1": [plan(1, "in-progress")]}, ["story/1"])
        self.assertEqual(row(b.derive(s), 1)["reviews"], {"bmad": 0, "fix_rounds": 0, "human": 0, "findings": None})

    def test_passes_and_findings_come_from_the_triage_log(self):
        p = {**plan(1, "built", review="thorough", loops=0), "review_passes": 2,
             "findings": {"found": 62, "patched": 27, "deferred": 2}}
        s = snap([ticket(1)], {"main": [], "story/1": [p]}, ["story/1"])
        r = row(b.derive(s), 1)
        self.assertEqual((r["reviews"]["bmad"], r["reviews"]["findings"]["found"]), (2, 62))
        self.assertIn("| 2/0/0 · 62 found, 27 patched, 2 deferred |", b.render_markdown(b.derive(s)))


TRIAGE = """---
ticket: '1'
status: built
---

## Review Triage Log

### Pass 1 — 2026-11-16 — high 0, medium 1

| # | Finding (lens) | Verdict | Route | Evidence |
|---|---|---|---|---|
| 1 | Errors get HTML (edge) | medium | bad_plan | Fixed. |
| 2 | A `a\\|b` gap (gap) | medium | patch | Added a test. |
| 3 | Odd host (blind) | maybe-false | defer | CI settles it. |
| 4 | Not a defect (blind) | false | rejected | Descriptive. |

### Pass 2 — 2026-11-17

| # | Finding (lens) | Verdict | Route | Evidence |
|---|---|---|---|---|
| 5 | Missing log (edge) | low | patch | Logged. |
| — | carried: rows 3 raised again | carried | as before | Still holds. |

## Design Notes

| # | Route |
|---|---|
| 9 | patch |
"""


class TriageLog(unittest.TestCase):
    def test_counts_passes_and_routes(self):
        self.assertEqual(b.triage_log(TRIAGE), (2, {"found": 5, "patched": 3, "deferred": 1}))

    def test_without_a_triage_log(self):
        self.assertEqual(b.triage_log("---\nticket: '1'\n---\n\n## Intent\n"), (0, None))

    def test_passes_without_a_readable_table(self):
        self.assertEqual(b.triage_log("## Review Triage Log\n\n### Pass 1\n\nNo findings.\n"), (1, None))

    def test_read_plans_carries_them(self):
        [p] = b.read_plans({f"{EPIC_PATH}/story-x-plan.md": TRIAGE})
        self.assertEqual((p["review_passes"], p["findings"]["patched"]), (2, 3))


NOW = 1_800_000_000  # 2027-01-15 08:00:00 UTC


def at(minutes_ago):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(NOW - minutes_ago * 60, timezone.utc).isoformat(timespec="seconds")


def lap(stage="in-progress", signals=None, branch_time=None, idle=None, quiet=600, here="story/1.1"):
    t = {**ticket(1), "ref": "1.1"}
    s = snap([t], {"main": [], "story/1.1": [plan(1, stage)]}, ["story/1.1"])
    s["now"] = NOW
    s["signals"] = {"1.1": signals or []}
    s["branch_times"] = {"story/1.1": NOW - branch_time * 60} if branch_time is not None else {}
    if idle is not None:
        s["activity"] = {"idle_seconds": {here: idle * 60}, "quiet_seconds": quiet}
    return row(b.derive(s), 1)


class Signals(unittest.TestCase):
    def test_a_lap_that_waits_needs_you_with_the_reason(self):
        r = lap(signals=[{"at": at(12), "state": "waiting", "kind": "approval", "text": "Approve the plan"}])
        self.assertEqual((r["status"], r["needs_you"]), ("needs you", "Approve the plan (approval, waiting 12 min)"))
        self.assertEqual(r["human_wait"], {"stops": 1, "seconds": 720})

    def test_working_again_ends_the_wait_and_keeps_the_time(self):
        r = lap(signals=[
            {"at": at(30), "state": "waiting", "kind": "permission", "text": "Subagents?"},
            {"at": at(25), "state": "working"},
            {"at": at(10), "state": "waiting", "kind": "approval", "text": "Approve the plan"},
            {"at": at(1), "state": "working"},
        ])
        self.assertEqual((r["status"], r["needs_you"], r["waiting_for_you"]), ("running", None, None))
        self.assertEqual(r["human_wait"], {"stops": 2, "seconds": 14 * 60})

    def test_a_newer_commit_makes_a_forgotten_wait_stale(self):
        r = lap(signals=[{"at": at(20), "state": "waiting", "kind": "approval", "text": "Approve the plan"}], branch_time=5)
        self.assertEqual((r["status"], r["waiting_for_you"]), ("running", None))
        self.assertEqual(r["human_wait"]["stops"], 1)

    def test_an_older_commit_does_not(self):
        r = lap(signals=[{"at": at(5), "state": "waiting", "kind": "choice", "text": "Split the plan?"}], branch_time=20)
        self.assertEqual(r["status"], "needs you")

    def test_a_wait_comes_before_the_built_ask(self):
        r = lap("built", signals=[{"at": at(2), "state": "waiting", "kind": "manual-step", "text": "Run gates by hand"}])
        self.assertEqual(r["needs_you"], "Run gates by hand (manual-step, waiting 2 min)")

    def test_a_wait_on_a_ticket_not_yet_branched(self):
        t = {**ticket(1), "ref": "1.1"}
        s = snap([t])
        s.update(now=NOW, signals={"1.1": [{"at": at(3), "state": "waiting", "kind": "question", "text": "This ticket?"}]})
        r = row(b.derive(s), 1)
        self.assertEqual((r["status"], r["needs_you"]), ("needs you", "This ticket? (question, waiting 3 min)"))

    def test_a_done_ticket_ignores_an_open_wait(self):
        t = {**ticket(1), "ref": "1.1"}
        s = snap([t], {"main": [plan(1, "done")]})
        s.update(now=NOW, signals={"1.1": [{"at": at(3), "state": "waiting", "kind": "limit", "text": "x"}]})
        self.assertEqual(row(b.derive(s), 1)["status"], "done")

    def test_unreadable_times_are_skipped(self):
        r = lap(signals=[{"at": "yesterday", "state": "waiting", "kind": "limit", "text": "x"}])
        self.assertEqual((r["status"], r["human_wait"]), ("running", None))


class Quiet(unittest.TestCase):
    def test_no_change_past_the_threshold_is_quiet(self):
        r = lap(idle=25)
        self.assertEqual((r["status"], r["needs_you"]), ("quiet", "Quiet for 25 min: look at the session"))

    def test_below_the_threshold_is_running(self):
        self.assertEqual(lap(idle=9)["status"], "running")

    def test_only_a_branch_checked_out_in_a_working_tree(self):
        self.assertEqual(lap(idle=25, here="story/1.6")["status"], "running")

    def test_a_named_wait_is_not_quiet(self):
        r = lap(idle=25, signals=[{"at": at(25), "state": "waiting", "kind": "approval", "text": "Approve"}])
        self.assertEqual(r["status"], "needs you")
        self.assertIsNone(r["quiet_minutes"])

    def test_quiet_wins_over_the_built_ask(self):
        self.assertEqual(lap("built", idle=15)["status"], "quiet")

    def test_in_ci_is_never_quiet(self):
        t = {**ticket(1), "ref": "1.1"}
        s = snap([t], {"main": [], "story/1.1": [plan(1, "built")]}, ["story/1.1"],
                 [pull(7, "story/1.1", checks={"gates": "running"})])
        s.update(now=NOW, activity={"idle_seconds": {"story/1.1": 3600}, "quiet_seconds": 600})
        self.assertEqual(row(b.derive(s), 1)["status"], "running")


class Problems(unittest.TestCase):
    def test_unknown_plan_status_is_reported_and_the_board_still_builds(self):
        board = b.derive(snap([ticket(1)], {"main": [], "story/1": [plan(1, "wip")]}, ["story/1"]))
        self.assertEqual(row(board, 1)["stage"], "Lap started")
        self.assertIn("unknown status `wip`", board["problems"][0])

    def test_a_branch_named_by_the_ticket_ref_matches(self):
        t1, t2 = {**ticket(1), "ref": "1.1"}, {**ticket(2), "ref": "1.2"}
        s = snap([t1, t2], branches=["story/1.2"], pulls=[pull(9, "story/1.2", checks=GREEN)])
        board = b.derive(s)
        self.assertEqual(board["problems"], [])
        self.assertEqual(row(board, 2)["pr"]["number"], 9)
        self.assertEqual(row(board, 1)["branch"], None)

    def test_branch_for_no_ticket(self):
        board = b.derive(snap([ticket(1)], branches=["story/99"]))
        self.assertEqual(board["problems"], ["Branch `story/99` matches no ticket."])

    def test_same_id_in_two_epics_is_ambiguous_until_the_plan_is_pushed(self):
        tickets = [ticket(1), ticket(1, epic="epic-other")]
        board = b.derive(snap(tickets, branches=["story/1"]))
        self.assertIn("several tickets", board["problems"][0])
        self.assertEqual(row(board, 1)["stage"], "Planned")

        plans = {"main": [plan(1, "done")], "story/1": [plan(1, "done"), plan(1, "in-progress", epic="epic-other")]}
        board = b.derive(snap(tickets, plans, ["story/1"]))
        self.assertEqual(board["problems"], [])
        self.assertEqual(row(board, 1, "epic-other")["stage"], "Building")
        self.assertEqual(row(board, 1)["stage"], "Done")


class Rendering(unittest.TestCase):
    def test_page(self):
        s = snap([ticket(1, "Walking | skeleton"), ticket(2, "Redirect", after=[1])],
                 {"main": [], "story/1": [plan(1, "built", review="thorough")]}, ["story/1"],
                 [pull(7, "story/1", checks={**GREEN, "gates": "red"})])
        md = b.render_markdown(b.derive(s))
        self.assertIn("# Board: r", md)
        self.assertIn("1 needs you · 1 waiting", md)
        self.assertIn("- **epic-shortlink #1** Walking \\| skeleton: Paste the failing check into the lap "
                      "(gates) → [#7](https://github.com/o/r/pull/7)", md)
        self.assertIn("| 1 | Walking \\| skeleton | In CI | needs you | Paste the failing check into the lap "
                      "(gates) | ❌✅✅ | 1/0/0 | [#7](https://github.com/o/r/pull/7) |", md)
        self.assertIn("| 2 | Redirect | Planned | waiting | – (after #1) | – | – | – |", md)
        self.assertIn("## Problems\n\nNone.", md)

    def test_empty_project(self):
        md = b.render_markdown(b.derive(snap([])))
        self.assertIn("No tickets yet.", md)
        self.assertIn("## Needs you now\n\nNothing.", md)


class Reading(unittest.TestCase):
    def test_frontmatter(self):
        text = ("---\ntitle: 'Walking skeleton: the page'\nticket: '1'\nstatus: in-review # draft | built\n"
                "review_loop_iteration: 2 # incremented\nblocked_reason: \"needs a # decision\"\nlenses_ran: []\n---\n\nstatus: built\n")
        fm = b.parse_frontmatter(text)
        self.assertEqual(fm["title"], "Walking skeleton: the page")
        self.assertEqual((fm["ticket"], fm["status"], fm["review_loop_iteration"]), ("1", "in-review", "2"))
        self.assertEqual(fm["blocked_reason"], "needs a # decision")
        self.assertEqual(b.parse_frontmatter("no frontmatter"), {})

    def test_tickets_and_plans_from_files(self):
        files = {
            "_bmad-output/init/tickets/tickets.toml": '[[epic]]\nid = "epic-shortlink"\n',
            f"{EPIC_PATH}/tickets.toml": '[[entry]]\nid = 1\ntitle = "Skeleton"\nafter = []\nhitl = false\n\n'
                                         '[[entry]]\nid = 2\ntitle = "Redirect"\nafter = [1]\n',
            f"{EPIC_PATH}/story-skeleton-plan.md": "---\nticket: '1'\nstatus: built\nreview: thorough\n---\n",
            "_bmad-output/init/tickets/broken/tickets/tickets.toml": "[[entry]\n",
        }
        problems = []
        tickets = b.read_tickets(files, problems)
        self.assertEqual([(t["epic"], t["id"], t["after"]) for t in tickets], [(EPIC, "1", []), (EPIC, "2", ["1"])])
        self.assertEqual(len(problems), 1)
        self.assertIn("broken", problems[0])
        plans = b.read_plans(files)
        self.assertEqual((plans[0]["epic"], plans[0]["ticket"], plans[0]["status"]), (EPIC, "1", "built"))

    def test_ticket_ref_comes_from_the_epic_table(self):
        files = {
            "_bmad-output/init/tickets/tickets.toml": f'[[epic]]\nid = 3\nslug = "{EPIC}"\n',
            f"{EPIC_PATH}/tickets.toml": '[[entry]]\nid = 2\ntitle = "Redirect"\nnotes = ["n1"]\n',
        }
        [t] = b.read_tickets(files, [])
        self.assertEqual((t["ref"], t["notes"], t["source"]), ("3.2", ["n1"], f"{EPIC_PATH}/tickets.toml"))

    def test_touches_and_post_merge(self):
        files = {f"{EPIC_PATH}/tickets.toml": '[[entry]]\nid = 1\ntouches = ["backend/**"]\n'
                                              '[[entry.post_merge]]\nwhat = "commit the lock"\n'
                                              'done_when = "file:harness/skeleton.lock"\n\n'
                                              '[[entry]]\nid = 2\n'}
        one, two = b.read_tickets(files, [])
        self.assertEqual(one["touches"], ["backend/**"])
        self.assertEqual(one["post_merge"], [{"what": "commit the lock", "done_when": "file:harness/skeleton.lock"}])
        self.assertEqual((two["touches"], two["post_merge"]), (None, []))

    def test_check_state(self):
        self.assertEqual(b.check_state("in_progress", None), "running")
        self.assertEqual(b.check_state("completed", "success"), "green")
        self.assertEqual(b.check_state("completed", "cancelled"), "red")


def decided(state="ready-to-implement", fresh=True, why="", questions=()):
    return {"state": state, "fresh": fresh, "why": why, "summary": "Because.", "questions": list(questions),
            "plan": "lap", "triaged_at": "2026-11-23T10:00:00+01:00"}


class Triage(unittest.TestCase):
    def derive(self, tickets, decisions):
        s = snap(tickets)
        s["triage"] = decisions
        return b.derive(s)

    def test_without_decisions_in_the_snapshot_the_lap_is_offered_as_before(self):
        self.assertEqual(row(b.derive(snap([ticket(1)])), 1)["needs_you"], "Start the lap")

    def test_an_untriaged_first_ticket_asks_for_triage(self):
        r = row(self.derive([ticket(1)], {}), 1)
        self.assertEqual((r["needs_you"], r["triage"]), ("Triage it (`triage 1`)", None))

    def test_a_stale_decision_says_why(self):
        r = row(self.derive([ticket(1)], {"1": decided(fresh=False, why="main changed a.java")}), 1)
        self.assertEqual(r["needs_you"], "Triage it (`triage 1`): main changed a.java")

    def test_ready_to_implement_offers_the_lap(self):
        self.assertEqual(row(self.derive([ticket(1)], {"1": decided()}), 1)["needs_you"], "Start the lap")

    def test_a_later_ticket_to_spec_needs_you_now(self):
        board = self.derive([ticket(1), ticket(2, after=[1])],
                            {"1": decided(), "2": decided("ready-to-spec", questions=["Which slugs are reserved?"])})
        r = row(board, 2)
        self.assertEqual(r["status"], "needs you")
        self.assertIn("`refine 2`", r["needs_you"])
        self.assertIn("Which slugs are reserved?", r["needs_you"])
        self.assertEqual(row(board, 1)["needs_you"], "Start the lap")

    def test_only_a_fresh_ready_to_implement_ticket_is_ready(self):
        board = self.derive([ticket(1), ticket(2), ticket(3), ticket(4)],
                            {"1": decided(), "3": decided(), "4": decided(fresh=False, why="main changed a.java")})
        self.assertEqual([row(board, i)["status"] for i in (1, 2, 3, 4)],
                         ["needs you", "untriaged", "ready", "untriaged"])
        self.assertEqual((board["counts"]["untriaged"], board["counts"]["ready"]), (2, 1))
        self.assertIn("2 untriaged", b.render_markdown(board))

    def test_every_stale_ticket_gets_a_hint(self):
        board = self.derive([ticket(1), ticket(2), ticket(3, after=[1])],
                            {"1": decided(fresh=False, why="a"), "2": decided(fresh=False, why="b"),
                             "3": decided(fresh=False, why="c")})
        self.assertEqual(row(board, 1)["needs_you"], "Triage it (`triage 1`): a")
        two, three = row(board, 2), row(board, 3)
        self.assertEqual((two["needs_you"], two["status"]), (None, "untriaged"))
        self.assertEqual(two["triage_hint"], "Stale (b): triage it again (`triage 2`), or the dispatcher will")
        self.assertEqual(three["status"], "waiting")
        self.assertIn("Stale (c)", three["triage_hint"])
        md = b.render_markdown(board)
        self.assertIn("– (Stale (b): triage it again", md)
        self.assertIn("(after #1) · Stale (c)", md)
        self.assertNotIn("Stale (b)", md.split("## Needs you now")[1].split("## ")[0])  # a hint, not a call

    def test_a_fresh_decision_leaves_no_hint(self):
        self.assertIsNone(row(self.derive([ticket(1)], {"1": decided()}), 1)["triage_hint"])

    def test_a_fresh_wait_needs_you(self):
        r = row(self.derive([ticket(1), ticket(2)], {"1": decided(), "2": decided("wait")}), 2)
        self.assertEqual(r["status"], "needs you")
        self.assertTrue(r["needs_you"].startswith("Triaged wait: Because."))

    def test_the_row_carries_the_plan_status(self):
        board = b.derive(snap([ticket(1), ticket(2)], plans={"main": [plan(1, "ready-for-dev")]}))
        self.assertEqual((row(board, 1)["plan_status"], row(board, 2)["plan_status"]), ("ready-for-dev", ""))


class Worktrees(unittest.TestCase):
    """Every lap runs in its own worktree; the live board says which, and when a file there last changed."""

    def snap_with_tree(self, idle=245):
        s = snap([ticket(1)], {"main": [], "story/1": [plan(1, "in-progress")]}, ["story/1"])
        s["worktrees"] = {"story/1": "/work/pilot-wt/story-1"}
        s["activity"] = {"idle_seconds": {"story/1": idle}, "quiet_seconds": 600}
        return s

    def test_a_lap_shows_its_worktree_and_last_change(self):
        r = row(b.derive(self.snap_with_tree()), 1)
        self.assertEqual((r["worktree"], r["last_change_minutes"]), ("/work/pilot-wt/story-1", 4))

    def test_without_worktrees_in_the_snapshot_nothing_is_shown(self):
        r = row(b.derive(snap([ticket(1)], {"main": [], "story/1": [plan(1, "in-progress")]}, ["story/1"])), 1)
        self.assertEqual((r["worktree"], r["last_change_minutes"]), (None, None))

    def test_a_quiet_lap_still_says_quiet(self):
        r = row(b.derive(self.snap_with_tree(idle=900)), 1)
        self.assertEqual((r["status"], r["last_change_minutes"]), ("quiet", 15))

if __name__ == "__main__":
    unittest.main()
