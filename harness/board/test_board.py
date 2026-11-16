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


def pull(number, branch, state="open", merged=False, checks=None, judged=1, human=0, holdouts=""):
    states = {c: {"state": s, "description": holdouts if c == "holdouts" else ""} for c, s in (checks or {}).items()}
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

    def test_built_without_pull_request_asks_for_one(self):
        s = snap([ticket(1)], {"main": [], "story/1": [plan(1, "built")]}, ["story/1"])
        r = row(b.derive(s), 1)
        self.assertEqual((r["stage"], r["status"]), ("Built", "needs you"))
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

    def test_holdouts_red_shows_only_ids(self):
        r = self.in_ci({**GREEN, "holdouts": "red"}, holdouts="failing: H-03 H-01")
        self.assertEqual(r["holdout_ids"], ["H-01", "H-03"])
        self.assertEqual(r["needs_you"], "Paste the failing check into the lap (holdouts: H-01, H-03)")

    def test_a_red_guard_comes_before_a_red_gate(self):
        r = self.in_ci({**GREEN, "gates": "red", "scope-guard": "red"})
        self.assertEqual(r["needs_you"], "Review the change: label it or send it back (scope-guard)")

    def test_all_green(self):
        self.assertEqual(self.in_ci(GREEN)["needs_you"], "Review and merge")

    def test_a_check_that_never_reported(self):
        r = self.in_ci({"gates": "green", "protected-paths": "green", "scope-guard": "green"})
        self.assertEqual(r["needs_you"], "A required check has not reported: holdouts")

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
        self.assertEqual(row(b.derive(s), 1)["reviews"], {"bmad": 2, "fix_rounds": 2, "human": 1})

    def test_no_review_yet(self):
        s = snap([ticket(1)], {"main": [], "story/1": [plan(1, "in-progress")]}, ["story/1"])
        self.assertEqual(row(b.derive(s), 1)["reviews"], {"bmad": 0, "fix_rounds": 0, "human": 0})


class Problems(unittest.TestCase):
    def test_unknown_plan_status_is_reported_and_the_board_still_builds(self):
        board = b.derive(snap([ticket(1)], {"main": [], "story/1": [plan(1, "wip")]}, ["story/1"]))
        self.assertEqual(row(board, 1)["stage"], "Lap started")
        self.assertIn("unknown status `wip`", board["problems"][0])

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
                 [pull(7, "story/1", checks={**GREEN, "holdouts": "red"}, holdouts="H-03")])
        md = b.render_markdown(b.derive(s))
        self.assertIn("# Board: r", md)
        self.assertIn("1 needs you · 1 waiting", md)
        self.assertIn("- **epic-shortlink #1** Walking \\| skeleton: Paste the failing check into the lap "
                      "(holdouts: H-03) → [#7](https://github.com/o/r/pull/7)", md)
        self.assertIn("| 1 | Walking \\| skeleton | In CI | needs you | Paste the failing check into the lap "
                      "(holdouts: H-03) | ✅✅✅❌ H-03 | 1/0/0 | [#7](https://github.com/o/r/pull/7) |", md)
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

    def test_check_state(self):
        self.assertEqual(b.check_state("in_progress", None), "running")
        self.assertEqual(b.check_state("completed", "success"), "green")
        self.assertEqual(b.check_state("completed", "cancelled"), "red")


if __name__ == "__main__":
    unittest.main()
