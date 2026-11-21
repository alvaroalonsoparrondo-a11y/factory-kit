# Changelog

Newest first. One entry per factory change: what was seen, where, and what changed. See [MODIFYING.md](MODIFYING.md).

## 2026-11-21 — The fence is off in the kit, on in projects

Seen in the kit: the fence that keeps a lap agent out of the factory files also blocked every agent session that was changing the kit itself, which is the kit's whole purpose. No laps run in the kit.

- **`fence/claude-settings.json` and `fence/kiro-factory.json` (new)** hold the fenced settings. `init-project.sh` copies them to `.claude/settings.json` and `.kiro/agents/factory.json` and deletes `fence/`, so every project starts fenced as before.
- **The kit's own `.claude/settings.json` and `.kiro/agents/factory.json`** deny only force pushes.
- **`judge-guards.yml`:** `protected-paths` skips a template repository (the kit). `scope-guard` is unchanged.
- **`FACTORY_RULES.md` section 2** says it applies in projects, not in the kit.
- **`MODIFYING.md`, `README.md`:** a fence change is made in `fence/` in the kit and moved to the live paths when carried to a project.
- **`AGENT_SETUP.md`:** the after-init check also expects `fence/` to be gone.

The `protected-paths` skip keys on GitHub's template flag. A project made from a local kit folder is not a template, so its guard runs. A kit on a host where it is not marked as a template keeps its guard; there the kit's pull requests still need `human-judge-change`.

## 2026-11-20 — GitHub Enterprise, a local kit, no Actions (from `my-factory-demo`)

Seen setting up `my-factory-demo` on github.axa.com with Kiro CLI, from a local clone of the kit. The kit assumed github.com everywhere: the template did not exist on the enterprise host, so step 1 stopped; `RUNBOOK.md` and the project `README.md` were filled in with `https://github.com/...` links; `serve.py` refused a non-github.com `origin`, and it and the dispatcher defaulted to `api.github.com`. Actions is not allowed there, so `gates` and `calibrate` never ran, and step 7 then required three checks that can never report: no pull request can merge except by an admin bypass. Setup also had no way to install BMAD for one agent only, and no answer when the environment names no co-author line.

- **`init-project.sh`** takes an optional third value, the host (default `github.com`), and fills in the new placeholder `__HOST__`, now used by the board link in `PROJECT_README.md` and `RUNBOOK.md` and by the kit remote.
- **`AGENT_SETUP.md`:** optional values HOST, KIT (a template, or a local folder whose `main` is pushed into an empty repository) and AGENTS. Every `gh` call names HOST. A rule: never change organisation policy (Actions, visibility, runners) to pass a step. Step 6 checks whether Actions may run; step 7 then leaves out the required checks. Stop and ask when a given URL and PROJECT disagree. Branch protection's JSON goes through a file, because a Windows pipe garbled it (HTTP 400 "Problems parsing JSON").
- **`RUNBOOK.md`:** a "Without GitHub Actions" section: the person runs `run-gates.sh`, reads the guard patterns, and runs `calibrate.sh` before each merge, and requires the pull request but not the checks. The kit remote may be a local folder.
- **`serve.py`, `dispatch.py`:** host, server and API root come from `origin` (`<server>/api/v3` on GitHub Enterprise); `gh auth token` asks for that host. `GITHUB_SERVER_URL` and `GITHUB_API_URL` still override.
- **`lap` skill (both copies):** the fallback pull request link takes its host from `origin`.
- **`README.md`, `MODIFYING.md`:** the host, local-kit and one-agent variants of the prompt and the kit remote; `__HOST__` in the placeholder list.

Tested: the board and serve tests (65) and dispatcher tests (46, one skipped) pass, with new cases for enterprise remotes; `init-project.sh` with a host on a scratch copy leaves no placeholder. Not tested: the new `AGENT_SETUP.md` end to end; the live board and dispatcher against a real GitHub Enterprise host.

Still open: the judge needs Actions, so where it is not allowed the checks are the person's own discipline. Running them elsewhere (AWS CodeBuild) is planned. BMAD's setup reports version `6.13.0-next` for both modules, while the kit says "BMAD v7"; not changed until it is clear which is right.

## 2026-11-19 — Kiro CLI can run interactive laps

Planned since the kit started (README "Planned"), and needed at work, where Kiro CLI is the agent and runs interactively only. Everything that tied the factory to Claude Code was in the agent set-up files; the judge and BMAD did not depend on the agent.

- **`AGENTS.md` (new) holds the agent instructions.** Kiro reads it by default. `CLAUDE.md` is now one line, `@AGENTS.md`, so the two cannot drift. `_bmad/custom/bmad-architecture.toml` reads the Layout line from `AGENTS.md`.
- **`.kiro/agents/factory.json` (new) is Kiro's fence:** `fs_write` deny on the same protected paths as `.claude/settings.json`, and `shell` deny on force pushes. It lives in the agent file because Kiro keeps workspace permission files outside the repository. Laps in Kiro run as `kiro-cli chat --agent factory`.
- **`.kiro/skills/lap/SKILL.md` (new) is a copy of the `lap` skill.** The `gates` workflow fails while the two copies differ. The lap's after-merge line no longer assumes the Claude desktop app to remove a worktree.
- **Protected paths** gain `AGENTS.md`, `.kiro/agents/` and `.kiro/skills/lap/`, in all five places (`FACTORY_RULES.md`, `.claude/settings.json`, `.kiro/agents/factory.json`, `CODEOWNERS`, `judge-guards.yml`).
- **BMAD** installs for both agents (`-a claude-code -a kiro-cli`). `RUNBOOK.md`, `AGENT_SETUP.md`, `MODIFYING.md` and `README.md` say how.

Not tested yet: a real lap in Kiro; that Kiro's `fs_write` deny matches these relative globs; that `skills add -a kiro-cli` installs BMAD where Kiro finds it. The dispatcher still starts headless laps with Claude Code only.

## 2026-11-19 — The agent may open any pull request; a human merges (from `factory-pilot`)

Seen in `factory-pilot`: only the lap could open its pull request, so factory changes and kit ports stopped at a pushed branch and the human opened each pull request by hand (this kit's #3 and #4).

- **`CLAUDE.md`:** open pull requests with `gh` when the work calls for one; the `lap` skill opens its own. Never label, approve or merge a pull request; a human does that.
- **`MODIFYING.md`:** the agent may open factory-change and kit-port pull requests; a human adds `human-judge-change` and merges.

## 2026-11-19 — Laps in worktrees, and the dispatcher (from `factory-pilot`)

Seen in `factory-pilot`, laps 1.3 and 1.6: the first parallel laps had to run in two full clones, because the lap required `main` checked out, and the lap had no step for a branch that falls behind `main`. The live board then lost sight of a lap running in a worktree: it read only its own folder live, so the lap looked frozen at its last push, its lap signals were never read, and one running lap kept every other one looking busy. Across laps 1.1 to 1.6 the human was also the event source and the orchestrator: picking, starting, pasting red checks, saying `merged`, and remembering follow-ups.

- **`lap` skill:** a lap runs in the main checkout or a worktree, branching from `origin/main`; gates run on a port (given, else `PORT`, else 8080 in the main checkout and 8081 in a worktree); new section D, "main moved" (merge, never rebase); section C works from a worktree. A dispatched lap finds its branch claimed, signals and ends where it would ask, and leaves C to the dispatcher.
- **Live board (`serve.py`, `board.py`):** reads plans and `.lap/` signals from every worktree, judges quiet per `story/*` worktree, skips nested worktrees when scanning, and reads a lap's pull request text from its own tree.
- **`harness/dispatch/dispatch.py` (new, with tests):** a local poller that claims a ready ticket once (creates `story/<ref>` on GitHub), gives it its own worktree and port, routes fix rounds (for every required check except the guards, as `board.py` lists them) and "main moved" rounds, and closes merged laps (mark done on `main`, remove the worktree, lap report line). `--no-agents` leaves every lap to a human (the shape for interactive-only agents such as Kiro); headless laps use `--permission-mode dontAsk` with an allow list and are refused while the fence is off. One pass at a time, `pause`, hung-lap reports and usage-limit resumes come from the Archon factory's live runs.
- **Planning:** tickets may carry `touches`, epic `shared` files and `[[entry.post_merge]]` actions; `bmad-agent-po.toml` asks for them. `.gitattributes` merges `deferred-work.md` with `union` and is now a factory file.

Tested in `factory-pilot`: board, serve and dispatcher unit tests; dry runs of the dispatcher on the pilot. In the kit, rebuilt on the holdouts removal: the same tests pass (the holdouts fix-round test is skipped, since the kit has no `holdouts` check). Not tested yet: a real dispatched lap, a real claim, closing a lap on GitHub.

## 2026-11-19 — The fence is back on (from `factory-pilot`)

Seen in `factory-pilot`: the fence came off on 2026-11-18 to make factory changes faster during the proof of concept. Once the dispatcher could run laps headless, an empty deny list meant such a lap had no guard at all, and the rules bound the agent by instruction only.

- **`.claude/settings.json`** has its deny list again: `MISSION.md`, `FACTORY_RULES.md`, `CLAUDE.md`, `harness/`, `.github/`, `.claude/settings.json`, the `lap` skill, `_bmad/custom/`, and force pushes. No holdouts rules, since the kit no longer has holdouts; `gh` stays allowed, since the lap opens its own pull request.
- **`FACTORY_RULES.md` section 2, `CLAUDE.md`, `MODIFYING.md` rules 1 and 2 and the porting step** are back to: a human makes factory changes, or a session they direct, on a `factory/` branch with a pull request labelled `human-judge-change`.
- **`RUNBOOK.md`, `README.md`, `AGENT_SETUP.md`** describe the fence again instead of an empty deny list.

Tested in `factory-pilot` (commit c112d0d): the dispatcher's fence check on a scratch repository refused a headless lap's edit to `harness/`, its write to `.claude/settings.json` and a force push, and allowed an ordinary edit.

## 2026-11-19 — Holdouts removed

Seen in `factory-pilot`, after tickets 1.1 to 1.6: the hidden-scenario side is most of the setup (a second repository, two fine-grained tokens, two variables, a `pull_request_target` workflow that dispatches across repositories) and had not yet caught anything the other checks missed. Its hiding was also weaker than it looked: the deny rules blocked the `Read` tool on the sibling folder but not a shell `cat`.

Changes:
- **`request-holdouts.yml`** deleted. The required checks are now `gates`, `protected-paths` and `scope-guard`.
- **Boards** (`board.py`, `dashboard.html`, `serve.py`): no `holdouts` column and no holdout IDs.
- **`FACTORY_RULES.md`**: section 4 "Holdouts stay hidden" removed; sections 5 and 6 become 4 and 5.
- **`lap` skill**: no holdouts rule and no holdouts fix round.
- **Setup** (`README.md`, `AGENT_SETUP.md`, `RUNBOOK.md`, `PROJECT_README.md`, `MODIFYING.md`): one repository per project; no tokens, no repository variables, no hidden-scenario session.
- `factory-kit-holdouts` is no longer used; archive it on GitHub.

What is lost: an independent check that the build matches the intent rather than only the agent's own tests. To bring it back, revert this entry's commit and un-archive `factory-kit-holdouts`.

Tested: the board tests (59 pass).

## 2026-11-18 — Lap signals: the live board shows when a running lap needs you

Seen in `factory-pilot`, lap 1.1 (2026-11-16 and 17): seven stops for a human, five of them only in the chat (permission for subagents twice, keep or split an oversized plan, approve the plan) and invisible on both boards. All five reviewers stopped on a usage limit and the lap sat for hours while the board said "In review". The review count showed 2 passes only because BMAD's loop counter, which counts loopbacks, happened to be 1; the 62 findings were not shown.

Changes:
- **`harness/board/lap_signal.py`** (new). `python harness/board/lap_signal.py <ref> waiting <kind> "<text>"` and `... <ref> working` add a line to `.lap/<ref>.jsonl`. Kinds: `permission`, `choice`, `approval`, `question`, `manual-step`, `limit`, `decision`.
- **`lap` skill.** One rule: signal `waiting` before any stop for the human, `working` after the answer.
- **Live board.** A waiting lap goes to "Needs you" with its reason and waiting time; a wait older than the branch's newest commit is ignored. A lap on the checked-out branch with no file change for 10 minutes (`--quiet-minutes`) shows as `quiet`. Cards show stops and total waiting time; the drawer lists the stops; the tab title starts with `(!) <n>`.
- **Both boards.** Review passes are the `### Pass` headings of the plan's Review Triage Log (fallback: the loop counter), with found / patched (`patch`, `bad_plan`) / deferred counted from its `Route` column.

Design: `docs/superpowers/specs/2026-11-17-ticket-board-v2-design.md`. Tested in `factory-kit`: 60 board tests; the triage logs of `factory-pilot`'s plans (lap 1.1: 2 passes, 62 found, 27 patched, 2 deferred); the live board's derivation on `factory-pilot`'s folder with a hand-made signal. Not tested yet: a real lap with the live board open.

## 2026-11-18 — Live board, lap opens its pull request, fence off, Java 21 (from `factory-pilot`)

Seen in `factory-pilot`, laps 1.1 and 1.2:
- The board reported "Branch `story/1.1` matches no ticket". The lap names branches by the ticket's ref (`<epic id>.<entry id>`) and the board matched the entry id alone, so a running lap and its pull request never showed on their ticket.
- Following a lap meant reading files by hand; `BOARD.md` only updates through CI and has no detail.
- The human created every pull request by hand, copying the title and body out of the chat.
- Every factory change needed a hand-made judge pull request, because the fence blocked each agent edit to a factory file. For a proof of concept this cost more time than it saved.
- The project moved to Java 21; the BMAD architecture config still said Java 17.

Changes:
- **Board matches lap branches.** `board.py` reads each epic's id from the `[[epic]]` table, gives every ticket its ref and matches `story/<ref>` first (a bare id still matches). Rows also carry `ref`, `risk` and `plan_path`.
- **Live board.** `harness/board/serve.py` and `dashboard.html` serve a local page (`python harness/board/serve.py`, then `http://127.0.0.1:8765`): columns of cards, and a drawer with each ticket's entry, plan, epic and pull request text. It reuses `board.py`, reads the checked-out branch from the working tree, caches GitHub for 60 s, and falls back to `gh api` when Python cannot verify GitHub's certificate (seen on Windows). `.claude/launch.json` starts it from the Claude desktop app.
- **The lap opens its pull request.** At the hand-over the lap writes the text to `.lap/<ticket id>-pr.md` (ignored by Git) and runs `gh pr create`; if `gh` fails it prints a link that opens the form filled in. A human still merges.
- **Fence off.** `.claude/settings.json` has an empty deny list. Outside a lap the agent may change factory files when the human asks, and factory changes may go straight to `main`. A lap still never changes factory files, weakens a test or reads the holdouts, and never labels, approves or merges. The setup checks in `AGENT_SETUP.md` and `RUNBOOK.md` no longer test that `MISSION.md` edits are refused.
- **Java 21.** The `gates` and `calibrate` workflows, `CLAUDE.md` and the RUNBOOK.
- **The BMAD config no longer names the stack.** `_bmad/custom/bmad-architecture.toml` restated "Java 17 and Spring Boot…" and was missed when the pilot changed stack. It now loads `CLAUDE.md` and says the stack is the one its Layout line names, so a stack change touches `CLAUDE.md` and the workflows, never `_bmad/custom`.

Tested in `factory-pilot`: 34 board tests; the live board on the real repository (PR #5 linked to 1.1, the drawer, the `gh api` fallback); lap 1.2 opened PR #6 itself, CI passed `gates`, `protected-paths` and `scope-guard`, and it merged. Not tested: a new project set up from the kit with the empty deny list.

## 2026-11-16 — Ticket board

Seen: the state of a ticket was split between BMAD files and GitHub tabs, and nothing showed what waited for a human.

- **`harness/board/board.py` and the `board` workflow added.** CI builds `BOARD.md` and `board.json` on a `board` branch: one row per ticket with stage, status, what it needs from a human, the four checks, and three review counts (BMAD passes / fix rounds / human reviews). Standard library only, no state of its own. Design: `docs/superpowers/specs/2026-11-16-ticket-board-design.md`.
- **`lap` skill pushes earlier.** The branch is pushed when the lap starts and again when the plan is approved, so a running lap is on the board. A lap that stops on an irreversible action marks the ticket blocked and pushes that.
- **`init-project.sh`** removes the kit's design documents from a new project.

Tested: 28 unit tests; a read-only dry run against `factory-pilot` (seven planned tickets) and `factory-trial` (no tickets). Tested on GitHub in `factory-trial` with three test tickets and a test pull request: first build from a push to `main`; lap started (empty branch); blocked lap with its reason; built with the compare link; in CI with a check that never reported; a red `protected-paths`; fix rounds counted after two more pushes; merged shown as done, which unlocked the next ticket. The push, pull request and finished-check triggers all fired.

Not yet tested on GitHub (unit tests only): a red `holdouts` with its IDs and the `status` trigger (both need the holdout tokens), a pull request closed without merge, the human review count, and two epics that share a ticket id. Cost per ticket was set aside.

## 2026-11-15 — First end-to-end setup test (`factory-trial`)

`AGENT_SETUP.md` was followed step by step to create a throwaway project. Steps 1–6 passed as written; step 7 was refused by GitHub (free plan, private repository), as the instructions expect.

Also checked on a trial pull request there: `protected-paths` and `scope-guard` went red on a change to `harness/` and a `security/` path, and green after the two approval labels were added; `gates` passed; pushes to `main` started `gates` normally.

Changes from the test:
- **Clear error when the dispatch secret is missing.** The holdouts request failed with a generic `gh` message; it now names the secret and variable to set.
- **A project gets its own README.** A new project kept the kit's README ("this repository is a template"). `init-project.sh` now swaps in `PROJECT_README.md` and removes the kit-only `AGENT_SETUP.md` and `CHANGELOG.md`.
- **`AGENT_SETUP.md` wording:** setup status `repaired` is fine; the exact refusal text for branch protection; push-triggered `gates` runs are expected.

Still untested: the hidden-scenario judge with real tokens, and a full lap. The missing push-triggered runs seen in `factory-pilot` did not happen in `factory-trial`; that looks specific to the pilot repository.

## 2026-11-15 — Agent setup prompt

- **`AGENT_SETUP.md` added; README prompt shortened.** The first version put all eight setup steps inside a prompt in the README. That duplicated `RUNBOOK.md` and would drift, so the steps moved to `AGENT_SETUP.md` and the prompt now only gives owner, project, folder and two guard rules, and points to that file. Pattern taken from the short install prompt of coleam00/ai-software-factory. Not yet run end to end.

## 2026-11-15 — First version

Made from the `factory-pilot` project before it had any product code.

- **Kit split from the project.** BMAD's own skills are no longer committed; each project installs them. Project names became placeholders, filled in by `init-project.sh`.
- **Maven cache removed from the workflows.** Seen in `factory-pilot`: the Java set-up step failed because no `pom.xml` exists before the walking skeleton.
- **Manual trigger added to `gates`.** Seen in `factory-pilot`: pushes to `main` did not start the workflow, so it could not be checked without one. Cause not found yet.
- **Action versions raised** to the current major versions, after deprecation warnings.
- **No separate reviewer agent.** BMAD v7's build already reviews with fresh subagents, so the factory adds one review lens ("Factory Judge") in `_bmad/custom/bmad-build.toml`.

### Known gaps

- No full lap has run yet. The pull request checks and the hidden-scenario judge are untested.
- Pushes to `main` did not start `gates` in `factory-pilot`; unexplained.
- The fence is a guard rail: a shell command can still reach a denied path.
- Claude Code and GitHub Actions only. Kiro and CodeBuild versions are planned.
