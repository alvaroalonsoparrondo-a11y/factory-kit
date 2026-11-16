# Ticket board: design

Date: 2026-11-16. Status: waiting for approval. Home: `factory-kit` (travels to projects like any factory change).

## Intent

A project runs several tickets through the factory. Today the state of a ticket is split between BMAD files and GitHub tabs. The board is one page per project that answers, for every ticket:

1. Which stage of the lap is it in?
2. What is its status?
3. Does it need a human, and for what?
4. How many times was it reviewed?

## Goals, non-goals, anti-goals

**Goals**

- One row per ticket, in build order, for every epic of the project.
- A "Needs you now" list at the top.
- Built by CI from existing sources. No store of its own.
- Viewable in the browser by anyone with access to the repository.

**Non-goals (for now)**

- Cost of a ticket (set aside by the owner on 2026-11-16).
- History, trends, charts, an HTML page.
- The CodeBuild variant for work. The script must not block it (see Constraints).
- Notifications.

**Anti-goals**

- The lap agent reporting its own progress to the board. Stages come from Git, GitHub and committed BMAD files only.
- Any text of a hidden scenario on the board. Only IDs such as `H-03`.
- A second copy of the tickets (issues, a project board, a database).

## Constraints

- `FACTORY_RULES.md` section 5: evidence comes from CI. The board builder is part of the judge, so it lives in protected paths (`harness/`, `.github/`).
- The lap agent never uses `gh` and never edits protected paths.
- Free GitHub plan, private repository: no GitHub Pages, so the output is a Markdown file on a branch.
- The script uses only the Python standard library (3.11+, for `tomllib`) and the GitHub REST API through `urllib`. No `gh`, no `uv`, no packages. It takes the repository, API base URL and token from the environment, so a CodeBuild project can run it later unchanged.
- The script reads checks by name from both check runs and commit statuses, so it does not care which CI produced them.

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| **A (chosen)** | CI rebuilds `BOARD.md` on a `board` branch on every push, pull-request change and finished check | Judge-side, nothing local, same page for everyone. Sees a lap only once something is pushed. |
| B | Local script writes an HTML page | Sees unpushed work, looks richer. Needs a token on the machine, only the runner sees it, stale until rerun. |
| C | GitHub Projects with tickets as issues | No code. Tickets live twice and drift; review counts and "needs you" still need automation. |

The owner chose A on 2026-11-16, with extra pushes from the `lap` skill so that a running lap is visible before the pull request.

## Design

### Parts

| File | Purpose |
|---|---|
| `harness/board/board.py` | Collects the data, derives one row per ticket, writes `BOARD.md` and `board.json` |
| `harness/board/test_board.py` + `harness/board/fixtures/` | Tests of the derivation, from recorded inputs |
| `.github/workflows/board.yml` | Runs the script and publishes the result |
| `.claude/skills/lap/SKILL.md` | Changed: early pushes, and a visible stop |
| `RUNBOOK.md`, `PROJECT_README.md`, `CHANGELOG.md` | Where the board is, how to rebuild it |

### Sources

| Data | Source |
|---|---|
| Tickets, order, `after`, `hitl`, `risk` | Every `_bmad-output/*/tickets/*/tickets/tickets.toml` on `main` (`[[entry]]` tables) |
| Plan status, block reason, review loop count | Frontmatter of the plan file `<type>-<slug>-plan.md` (`ticket`, `status`, `review`, `review_loop_iteration`, the block field written by `tickets.py mark --blocked`), read from `origin/story/<id>` when that branch exists, else from `main` |
| Lap branch | Remote branches named `story/<id>` |
| Pull request, labels, merge, human reviews | GitHub REST: pulls for the branch, and their reviews |
| Checks | Check runs and commit statuses on the pull request's head commit, by name: `gates`, `protected-paths`, `scope-guard`, `holdouts` |
| Failing hidden scenarios | The description of the `holdouts` commit status, which already holds IDs only |

The script parses the BMAD files itself and does not call `tickets.py`. That keeps `uv` and the BMAD skills out of CI. The cost is that a BMAD format change can break it, so an unknown plan status or an unreadable file goes into a "Problems" section at the bottom of the board and does not stop the build.

### Stages

| Stage | Rule |
|---|---|
| Planned | No `story/<id>` branch |
| Lap started | Branch exists, no plan yet or plan `draft` / `ready-for-dev` |
| Building | Plan `in-progress` |
| In review | Plan `in-review` |
| Built | Plan `built`, no pull request |
| In CI | Pull request open |
| Done | Pull request merged, or plan `done` on `main` |
| Dropped | Plan `dropped` |

A merged pull request counts as done. The board does not wait for the local "mark done" step, because that commit reaches `origin/main` only when a human pushes it.

### Status

One word per row, first match wins:

| Status | Rule |
|---|---|
| `dropped` | Stage is Dropped |
| `done` | Stage is Done |
| `blocked` | Plan is blocked |
| `needs you` | Any other "Needs you" rule below matches |
| `running` | A branch exists and nothing is asked of a human (lap at work, or checks still running) |
| `waiting` | Planned, and a ticket in `after` is not done |
| `ready` | Planned, prerequisites done, but an earlier ticket is first in line |

### Needs you

First matching rule wins.

| Condition | Text on the board |
|---|---|
| Plan is blocked | Decide: `<reason>` |
| Pull request closed without merge | Closed without merge: decide what happens to the ticket |
| Pull request open, `protected-paths` or `scope-guard` red | Review the change: label it or send it back |
| Pull request open, `gates` or `holdouts` red | Paste the failing check into the lap |
| Pull request open, all four checks green | Review and merge |
| Built, no pull request | Open the pull request (with the compare link) |
| Planned, prerequisites done, first such ticket in build order | Start the lap (adds "human in the loop" when `hitl` is true) |
| Anything else | – |

### Reviews

Three numbers per ticket, shown as `B / F / H`:

- **B, BMAD review passes:** `review_loop_iteration + 1` once the plan reached `in-review` with `review` other than `none`; otherwise 0.
- **F, fix rounds:** commits of the pull request that have a `gates` result, minus one.
- **H, human reviews:** submitted reviews on the pull request by human accounts.

### The page

`BOARD.md` on the `board` branch:

```
# Board: factory-pilot
Built from main abc1234 · 3 done · 1 running · 1 needs you · 2 waiting

## Needs you now
- #3 Create a link with a random slug: paste the failing check into the lap (gates) → PR #7

## epic-shortlink
| # | Ticket | Stage | Status | Needs you | Checks | Reviews B/F/H | PR |
|---|---|---|---|---|---|---|---|
| 1 | Walking skeleton | Done | done | – | ✅✅✅✅ | 2/1/1 | #4 |
| 3 | Create a link, random slug | In CI | needs you | Paste the failing check | ❌✅✅⏳ | 1/0/0 | #7 |
| 4 | Custom slug | Planned | waiting | – (after #3) | – | – | – |

## Problems
None.
```

The checks column is always in the order `gates`, `protected-paths`, `scope-guard`, `holdouts`. A red `holdouts` shows its IDs, for example `❌ H-03`. `board.json` holds the same rows as data, for a richer page or a cost column later.

### The workflow

`board.yml` rebuilds on:

- push to `main` and to `story/**`;
- pull request opened, reopened, closed, labeled, unlabeled or updated (`pull_request_target`);
- `gates` or `judge-guards` finished (`workflow_run`);
- a commit status arriving (`status`, for `holdouts`);
- a manual run (`workflow_dispatch`).

It always checks out `main` to get the script, fetches all `story/*` branches, runs the script with the built-in token, and commits the two files to the `board` branch when they changed. Permissions: write to contents, read on pull requests, checks, statuses and actions. Runs are serialised. A push made with the built-in token starts no workflow, so there is no loop.

### Changes to the `lap` skill

- **A.5 Branch:** after `git switch -c story/<id>`, push the branch at once (`git push -u origin story/<id>`). The board shows "Lap started".
- **A.6 Build:** when the BMAD plan is approved, commit the plan file and push. The board shows "Building".
- **A.4 Irreversible check:** on a stop, create and push the branch, mark the ticket blocked with the rule as reason (`tickets.py mark <ref> draft --blocked "<rule>"`), commit, push, then stop. The board shows "Decide: …".
- **A.8 Push:** unchanged in effect; the upstream is already set.

`gates` runs on pull requests, not on branch pushes, so the extra pushes start only the board rebuild.

## Known limits

- Work that is not pushed is invisible. With the early pushes this is only the time before the first push.
- With several epics, ticket ids repeat. The board matches a `story/<id>` branch to its epic through the plan file on the branch. Before a plan exists, an ambiguous branch is listed under "Problems".
- The workflow file on a `story/**` branch is the one that runs for that push, as with every Actions workflow. The fence and `protected-paths` cover this as they do for `gates`.
- Pushes to `main` in `factory-pilot` do not start `gates` today, for an unknown reason. The board has other triggers and a manual run, and the rollout tests this first.

## Rollout

1. Build in `factory-kit` as factory-only commits; add a `CHANGELOG.md` entry.
2. Cherry-pick into `factory-trial` and test there with a dummy `story/1` branch and pull request: every trigger, every stage, one red check, one blocked ticket.
3. Cherry-pick into `factory-pilot` before its first lap.

## Left to the builder

- The exact frontmatter field `tickets.py mark --blocked` writes, and how the plan file is located on a branch.
- Whether the mid-build push (after plan approval) fits `bmad-build`'s flow. If it does not, keep only the first early push and drop the "Building" stage's early visibility.
- Queueing versus cancelling of overlapping board runs.
- Whether `init-project.sh` should remove `docs/superpowers/` from new projects.
