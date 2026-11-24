# Lap signals: show on the live board when a running lap needs you

Date: 2026-11-17, rewritten 2026-11-18. Status: waiting for approval. Home: `factory-kit`.

> **Note, 2026-11-24 (issue #40):** the GitHub board has since been removed: the `board` workflow, `BOARD.md` and the `board` branch. The live board is the only board. What this spec says about the GitHub board, `BOARD.md` and the `board` workflow is history; the `harness/board` tests now run in the `gates` workflow.

Builds on the ticket board (first designed on 2026-11-16) and on the live board (`harness/board/serve.py` and `dashboard.html`) that came from `factory-pilot` on 2026-11-18. Both boards stay:

- **GitHub board** (`BOARD.md` on the `board` branch, built by CI): for the team. It shows what is pushed.
- **Live board** (`python harness/board/serve.py`, at `http://127.0.0.1:8765`): for the person running the lap. It also reads the working tree.

The first version of this spec proposed a separate local page, `lap_view.py`. The live board now does most of that, so this version only adds what is still missing.

## Why

Lap 1.1 in `factory-pilot` (2026-11-16 and 17) had seven stops for a human. Neither board shows five of them today.

| What happened in lap 1.1 | What the boards show today |
|---|---|
| BMAD asked for permission to use subagents (twice) | Nothing |
| BMAD asked whether to keep or split an oversized plan, and asked for approval of the plan | Nothing |
| All five reviewers stopped on a usage limit, and the lap sat for hours | "Building" or "In review", as if work were going on |
| Two review passes, 62 findings, 27 patched, 2 deferred | `B2` only because the loop counter happened to be 1; findings are not shown |

The live board already covers the rest: it reads the plan from the working tree before the push, follows BMAD's plan status, matches `story/<epic id>.<ticket id>`, and shows pull requests and checks.

## Intent

The owner wants to know **whether a human is needed during the lap**, and why. Today "Needs you" starts only after the push, when the PR has to be opened, a check is red or a ticket is blocked. This spec extends it to the stops that happen in the chat, and to a lap that has stopped without saying so.

## Goals, non-goals, anti-goals

**Goals**

- The live board shows that the running lap waits for a human, and the reason.
- A lap that has gone quiet shows as quiet, without help from the agent.
- The time a ticket spent waiting for a human is visible.
- Both boards count review passes from the plan's triage log and show what the passes found.
- The browser tab shows "(!)" when something waits for you.

**Non-goals**

- Sending lap signals to GitHub. The team sees the lap from the pushed branch and the PR, as it does today.
- Cost per ticket.
- Desktop notifications or sound.

**Anti-goals**

- Treating what the lap says about itself as evidence. Only the checks on the pull request judge the work.
- New branches, scheduled runs or workflow runs.
- Committing anything from `.lap/`.

## Design

### 1. The one thing the agent must say: "I am waiting"

A stop for a human exists only in the chat, so the lap has to write it down.

- A new helper, `harness/board/lap_signal.py`, owned by the human, standard library only. The agent may run it and may not change it.

  ```
  python harness/board/lap_signal.py <ref> waiting <kind> "<what is needed>"
  python harness/board/lap_signal.py <ref> working
  ```

- It adds one JSON line to `.lap/<ref>.jsonl`, next to the `.lap/<ref>-pr.md` the lap already writes: `{"at": "<ISO time>", "state": "waiting" | "working", "kind": "...", "text": "..."}`. `.lap/` is already in `.gitignore`.
- It rejects an unknown state or kind with exit code 2, so a typo cannot slip through.
- The file is the ticket's timeline of stops.

**Kinds**, from the stops in lap 1.1 and the `lap` skill's own stops:

| Kind | Example |
|---|---|
| `permission` | "May I use subagents for this lap?" |
| `choice` | Keep or split an oversized plan; split a ticket with several goals |
| `approval` | Approve the plan |
| `question` | An open question the plan cannot settle |
| `manual-step` | Run the reviewers by hand; open the pull request; paste a failing check |
| `limit` | Still red after 3 fix rounds; more than five review loops |
| `decision` | An irreversible action under `FACTORY_RULES.md` section 1 |

**One rule added to the `lap` skill:** before stopping to wait for the human, for any reason, run `lap_signal.py <ref> waiting <kind> "<what is needed>"`. When the human has answered, run `lap_signal.py <ref> working` before continuing. The final hand-over ("the lap now waits for CI and the human") needs no signal, because the PR shows it.

### 2. What the board does with a signal

`serve.py` reads `.lap/*.jsonl` and attaches each ticket's timeline to its row. `board.py` turns it into the row's fields, so the logic is tested with the rest of `derive`:

- **Waiting:** if the newest signal is `waiting`, the row gets `needs_you = "<text> (<kind>, waiting <n> min)"` and status `needs you`. The card moves to the existing "Needs you" column. This takes precedence over what GitHub says, because the lap is stopped either way.
- **Stale wait:** a `waiting` signal is ignored once the ticket's branch has a commit newer than the signal (the lap evidently went on), or once the ticket is Done or Dropped. This check does not depend on the agent remembering to signal `working`.
- **Human wait:** the number of stops, and the total time from each `waiting` to the next `working` (or to now, if the lap is still waiting), shown as `2 stops · 14 min` on the card and in the drawer.

The GitHub board ignores signals. CI never sees `.lap/`, and `board.py` without a timeline behaves as it does now.

### 3. A lap that went quiet

The agent cannot report a usage limit, a crash or a permission prompt from the tool. The board sees it anyway.

- **Activity** means the newest change time of any file in the working tree, including ignored build output (`target/`, `test-results/`) because the local gates write there. It skips `.git/`, `node_modules/` and `.lap/`. `serve.py` checks it every 30 seconds, not on every refresh.
- **Quiet** means: the ticket's branch is the one checked out here, its stage is Lap started, Building, In review or Built, its newest signal is not `waiting`, and nothing has changed for more than the threshold. The threshold is 10 minutes by default; `serve.py --quiet-minutes` changes it.
- The row gets status `quiet` and `needs_you = "Quiet for <n> min: look at the session"`. The card goes to "Needs you" with a `quiet` flag.
- In lap 1.1, the longest stretch without a file change while the lap was working was a review pass, about 2 minutes, so 10 minutes should not raise false alarms. The first laps will show whether long gate runs need a higher threshold.

### 4. Review passes and findings (both boards)

BMAD's `review_loop_iteration` counts only loopbacks: lap 1.1 had two passes and a counter of 1. The plan's Review Triage Log is the better source.

- `read_plans` also reads the plan body: the number of `### Pass` headings in the triage log, and the findings counted from its `Route` column (found, patched, deferred).
- `reviews.bmad` becomes the pass count. Without a triage log it falls back to `review_loop_iteration + 1`, as today.
- A new `reviews.findings` holds `{found, patched, deferred}`, or nothing if the table cannot be read. BMAD does not fix the table's layout, so the counts are best effort.
- `BOARD.md` shows passes as today and adds the findings to the review cell. The live board shows them in the `B…` chip's tooltip and in the drawer.

The plan is pushed when it is approved and when the lap ends, so the team sees the counts on the GitHub board too.

### 5. The page

- The tab title becomes `(!) <n> · Factory Board` when any card is in "Needs you" for a reason other than "Start the lap". This includes waiting, quiet and blocked tickets, and PRs that need you. With nothing to do, the title stays `Factory Board`.
- Cards show the reason text and the waiting time. The drawer's ticket document gets the stops from the timeline: time, kind, text, how long each one lasted.
- The page says that "waiting" is the agent's own report.

### 6. Trust

- The "waiting" line is the agent's own word. A lap can hide a wait or invent one; it cannot use either to change what the checks decide.
- The quiet rule and the stale-wait rule do not depend on the agent. A lap that claims to be working but changes nothing still shows as quiet.
- Neither board is evidence. The checks on the pull request are.

## What changes

| File | Change |
|---|---|
| `harness/board/lap_signal.py` and its tests | New |
| `harness/board/board.py` and `test_board.py` | Timeline fields (waiting, stale wait, human wait, quiet) in `derive`; passes and findings from the triage log; findings in `BOARD.md` |
| `harness/board/serve.py` and `test_serve.py` | Reads `.lap/*.jsonl` and the activity time; `--quiet-minutes` |
| `harness/board/dashboard.html` | "(!)" title, reason and wait on cards, `quiet` flag, stops in the drawer |
| `.claude/skills/lap/SKILL.md` | The waiting rule |
| `RUNBOOK.md`, `CHANGELOG.md` | What the new statuses mean, how to set the threshold |

Nothing new in `.github/`. The `board` workflow keeps running the same script and tests.

## Known limits

- A stop the agent forgets to signal shows as "quiet" after the threshold, not as a named wait.
- A permission prompt from the tool freezes the agent mid-action. It also shows as quiet.
- Quiet is only judged for the branch checked out in the folder `serve.py` runs in. A lap in another clone or worktree needs its own `serve.py --root`.
- The triage log's layout is not fixed by BMAD, so finding counts are best effort.
- Lap 1.1 is one lap, of the largest kind of ticket. The kinds and the quiet threshold may need adjusting.
- At work, the Kiro version of the lap instructions needs the same waiting rule.

## Rollout

1. Build in `factory-kit` as factory-only commits.
2. Try it against `factory-pilot`'s folder as it is: lap 1.1's plan has a two-pass triage log, which tests the review counts. Write a few signals by hand to test waiting, stale wait and quiet.
3. Bring it into `factory-pilot` as a judge-change pull request, and run the next lap with the live board open.
