# Early intent approval — implementation plan

Design: [docs/specs/2026-11-24-early-intent-approval-design.md](../specs/2026-11-24-early-intent-approval-design.md). Branch: `factory/early-intent`.

One rule drives every task: **a prepared ticket's lap never waits for the human; an unprepared ticket's lap behaves as on `main` today.**

A ticket is **prepared** when its leaf file (a `.md` in the epic's `tickets/` folder whose frontmatter `id` is the entry's) has `refined: true`, and its triage is a fresh `ready-to-implement`.

## Task 1 — `triage.py`: say whether a ticket is prepared

Files: `template/harness/board/triage.py`, `template/harness/board/test_triage.py`.

- Add `leaf_file(root, rev, ticket) -> (path, frontmatter) | None`, the leaf file `ticket_texts` already finds (factor the lookup out so both use it).
- Add `prepared(root, rev, ticket, record, fresh) -> path | None`: the leaf file's path when `fresh`, `record["state"] == "ready-to-implement"` and the leaf's `refined` is `true` (case-insensitive, quotes stripped); else `None`.
- `statuses()` adds `"prepared": <leaf path or None>` to each entry.
- `check` keeps its first line as it is. For a prepared ticket, the second line is `prepared: <leaf path>` instead of `plan: …`. Otherwise the output is unchanged.
- Tests (scratch repository, like the existing ones):
  - fresh `ready-to-implement` + leaf `refined: true` → prepared, `check` prints `prepared: <path>`;
  - leaf `refined: false`, no leaf file, stale decision, or another route → not prepared, `check` output unchanged from today;
  - `risk = "high"` + refined leaf → still prepared (the plan line no longer says "a human approves it").

## Task 2 — Lap skill: self-approve a prepared plan, hand back instead of waiting

Files: `template/.claude/skills/lap/SKILL.md`, copied to `template/.kiro/skills/lap/SKILL.md` (they must stay byte-identical).

- **Step 3**, the triage read: add the case `prepared: <leaf path>` → "the ticket is prepared: the plan is yours to approve in step 6, and nothing in this lap may wait for the human; where it would, hand back (section E)". Keep the two existing cases word for word for unprepared tickets.
- **Step 6**, add a bullet before "Approving the plan yourself":
  - **Prepared ticket:** when `bmad-build` writes the plan, its `<frozen-after-approval>` block carries the leaf file's numbered criteria and Boundaries as they are (under the I/O matrix's heading, or a `## Acceptance (from <leaf path>)` heading inside the block). At CHECKPOINT 1, if the plan has no `## Open Questions`, choose **Approve and continue** and put `Plan approved by prepared ticket (<leaf path>)` in the plan's commit message. If it has open questions, hand back (section E). Later, an `intent_gap` in review also hands back.
- **New section E — Hand back (prepared tickets only):**
  1. `git fetch origin`, then in a throwaway detached worktree of `origin/main`: `tickets.py mark <ref> draft --blocked "Handed back by the lap: <the questions, one line each>"`, commit `Hand back ticket <ref>: <first question>`, `git push origin HEAD:main` (rebase once on a refused push, never force).
  2. `git push origin --delete story/<ref>`.
  3. Report one line: the ticket was handed back, with the questions. No `lap_signal.py waiting`: nothing in the lap waits.
  - Never open a pull request on a handed-back lap. A hand-back takes no round.

## Task 3 — `bmad-build.toml`: the same rule from `bmad-build`'s side

File: `template/_bmad/custom/bmad-build.toml`.

- Extend the CHECKPOINT 1 fact: "When the lap skill says the ticket is prepared (`triage.py <ref> check` prints `prepared: <leaf path>`), copy the leaf's numbered criteria and Boundaries into the `<frozen-after-approval>` block as they are; never write an Open Question the leaf already answers. With no Open Questions the lap approves; with any, and on an `intent_gap` in review, HALT and return to the lap skill, which hands the ticket back. Do not ask the human."
- Leave the existing triage self-approval fact as it is for unprepared tickets.

## Task 4 — Dispatcher: close a handed-back lap

Files: `template/harness/dispatch/dispatch.py`, `template/harness/dispatch/test_dispatch.py`.

Today a lap whose ticket is blocked halts with "blocked: … Then `dispatch.py release`", and the run stays in memory, so the ticket is never claimed again.

- In `_route`, before the `r["blocked"]` halt: when the process has exited, `origin/story/<ref>` no longer exists and the ticket is blocked on `main` with a reason starting `Handed back by the lap`, treat it as a **hand-back**: remove the worktree (`repo.remove_worktree`), drop the run, append a lap-report line (`handed back: <reason>`), and report it under `needs_you` with the reason and "answer in the ticket, then clear the block (`tickets.py mark <ref> draft`)".
- After that the ticket is an ordinary blocked one: never claimed while blocked; once unblocked and edited, its triage is stale and it is triaged again.
- Tests: a hand-back closes the run and frees the worktree; the ticket is not claimed while blocked; after unblocking with a fresh `ready-to-implement` decision it is claimed again; a lap blocked for another reason still halts as today.

## Task 5 — Live dashboard: show "prepared"

Files: `template/harness/board/dashboard.html`. No change to `board.py`'s rendering of `BOARD.md`, nor to `board.yml`.

- The row's `triage` already reaches the page through `serve.py`; it now carries `prepared` (Task 1).
- Card: when `r.triage?.prepared`, the triage meta shows `prepared` instead of `triage: ready-to-implement`.
- Drawer's triage block: when prepared, the head says `plan approved by: the lap (prepared: <leaf path>)` instead of the `plan` line.
- Check it in the browser with a fake board, as the last dashboard change did; there is no JS test harness.

## Task 6 — RUNBOOK and changelog

Files: `template/RUNBOOK.md`, `CHANGELOG.md`.

- RUNBOOK, after the triage section, **"Prepare the next ticket while a lap runs"**: refine it with Sofia (`refine <ref>`, which writes the leaf file with criteria and `refined: true`); it is triaged again; a prepared ticket's lap never asks you anything; if its plan needs you anyway, it hands the ticket back to Needs you with the questions; answer in the ticket and clear the block. A ticket you did not prepare works as before.
- CHANGELOG entry: what was seen (plan review during the lap, factory-pilot-2), what changed, tests, and what is not covered (no real prepared lap has run yet).

## Order and checks

1 → 2 and 3 (together) → 4 → 5 → 6. After each task, run the harness tests it touches; at the end, all of them (`bin`, `board`, `dispatch`, `judge`, `runtime`) and `kit.py doctor` on a scratch project, so the two lap skill copies are checked.

## Not in this plan

- Any change to the CI board (`BOARD.md`, `board.yml`): it is to be removed.
- Changing the "what" during a lap.
- A real prepared lap end to end: that is the first run in `factory-pilot-2` after `kit.py sync`.
