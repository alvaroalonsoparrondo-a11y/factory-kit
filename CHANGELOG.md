# Changelog

Newest first. One entry per factory change: what was seen, where, and what changed. See [template/MODIFYING.md](template/MODIFYING.md). Projects keep no factory changelog; this is the only one.

## 2026-11-23 — A hand triage is recorded on `main` without a manual commit (from `factory-pilot-2`)

Seen in `factory-pilot-2`, re-testing kit `76aeda9` on ticket 1.2: after a hand triage, `triage.py record` wrote `docs/triage/<ref>.json` into the checkout and the skill told the human to commit it to `main`. That was a step outside the lap and its pull request, and only a commit on `main` lets anything read the decision. The dispatcher already commits its own triages straight to `main`.

- **`harness/board/triage.py`:** `record --push` fetches, checks the decision against `origin/main` and commits `docs/triage/<ref>.json` straight onto `main` from a throwaway detached worktree, so no checkout changes. If `main` moved, it rebases its one commit and pushes again, and it never force-pushes. It refuses any `--rev` other than `origin/main`. Without `--push` it behaves as before.
- **Shared code:** the commit-to-main helper moved from `dispatch.Repo._commit_to_main` to `triage.commit_to_main`. The dispatcher calls it for triages and for marking tickets done, so both paths commit the same way.
- **`triage` skill** (both copies): on the human's yes in chat, the agent runs `record --push` and shows the output. It never writes, commits or pushes a decision any other way.
- **RUNBOOK:** nobody commits a decision by hand any more.
- **Tests:** `test_triage.py` gains 2 tests: a push to a scratch bare origin that leaves the checkout alone and gives a fresh decision on `origin/main`, and a refused `--rev`.

## 2026-11-23 — Triage: each ticket's route is decided before its lap (from `factory-pilot-2`)

Seen in `factory-pilot-2`, lap 1.2: the lap stopped halfway for planning. `bmad-build`'s CHECKPOINT 1 waited for a human to approve the plan, so the factory could not build one ticket while the human planned the next. The board's first column read "Backlog — planned" though no ticket in it had a plan. Planning a ticket fully in advance was rejected: its code plan goes stale once the ticket before it merges. The split kept is "settle the intent early, write the code plan at lap time". After warpdotdev-demos/cloud-factory-demo's `triage` skill, with BMAD tickets in place of GitHub issues.

- **`triage` skill** (`.claude/skills/triage/`, copied to `.kiro/skills/triage/`): read-only. It reads the ticket, its epic, `MISSION.md`, the code on `main` and the board, and answers one JSON object with one route: `ready-to-implement`, `ready-to-spec`, `needs-info` or `wait`. When unsure, it picks the more cautious route.
- **`harness/board/triage.py`:**
  - `record` checks the answer and writes `docs/triage/<ref>.json`. The file carries the commit it was made on, a fingerprint of the ticket (its entry, leaf file and epic file) and which prerequisites were done.
  - `check` says `none`, `fresh <route>` or `stale <route>: <why>`. A decision goes stale when the ticket or its epic changes, a prerequisite is done, or `main` changes a path in the ticket's `touches`.
  - A `ready-to-implement` decision on an entry with `risk = "high"` or `hitl = true` still has a human approve the plan.
- **Dispatcher:**
  - It triages the next ticket in line (every prerequisite done or in flight) when its decision is missing or stale. The triage runs as a headless agent limited to `Read Glob Grep Skill`, in a detached worktree of `origin/main`, one at a time. The dispatcher commits the decision to `main`, the way it marks a ticket done (`Repo._commit_to_main`, now shared).
  - It claims only tickets whose decision is a fresh `ready-to-implement`. Other routes go to Needs you with their questions.
  - A failed triage stops until `dispatch.py release <ref>`; a usage limit is tried again after 30 minutes. With `--no-agents`, it asks the human to triage.
- **Lap:** step 3 reads `triage.py <ref> check`. On a fresh `ready-to-implement` with `plan: the lap approves it`, the lap approves its own plan at CHECKPOINT 1, but only when the plan has no open questions and its intent matches the triage. `_bmad/custom/bmad-build.toml` says the same. Every other case waits for the human, as before. The pull request states the route and who approved the plan.
- **Board:**
  - A ticket's decision shows on its card (`triage: <route>`, or `stale`). `ready-to-spec` and `needs-info` cards move to Needs you, for any ticket, not only the next one.
  - The first ticket with no fresh decision says "Triage it". The Backlog column's subtitle is now "triage".
  - Snapshots without decisions (CI's `board.yml`) behave as before.
- **Protected:** the triage skill is a protected path in `FACTORY_RULES.md`, `guards.json`, both fences and the seed `CODEOWNERS`. `kit.py doctor` checks that the Kiro copy matches, as for the lap skill. `docs/triage/` is the project's, like `docs/runtime/`.
- **Tests:** `test_triage.py` (14, on a scratch repository), 11 dispatcher tests, 5 board tests.
- **Not done:** the judge and `gates.yml` still compare only the lap skill's two copies; `kit.py doctor` covers the triage skill's.
## 2026-11-23 — Setup, planning and the skeleton lap, from the first full run (from `factory-pilot-2`)

Seen in the first planning-to-lap run of `factory-pilot-2` (Shortlink), 2026-11-22 to 23, on BMAD `6.13.0-next`. Each item is numbered as in the project's feedback.

- **Setup that nothing reported (1, 3).** GitHub Actions was off, so the first pull request merged with no checks at all; nobody noticed until the second.
  - **`kit.py doctor`** now ends with `open:` lines for each setup step still open. It asks GitHub, through `gh` and the host and repository from `origin`, whether:
    - Actions is on (if not, it points to the judge);
    - the three labels exist;
    - `main` is protected and requires the three checks (or protection is not available on the plan).

    Locally it checks that BMAD is installed, that an active initiative is set, and that no skill folder is a symlink. These lines never fail `doctor`. `kit.py init` runs it at the end; `--offline` skips GitHub; `sync` asks GitHub nothing.
  - **The BMAD install** in `RUNBOOK.md` and `AGENT_SETUP.md` adds `--copy`. Without it, the skills CLI keeps the skills in `.agents/skills/` and links the agents' folders to it, which is the untracked `.agents/` (528 files) the pilot found. Ignoring `.agents/` alone would commit broken links on Linux and macOS (tried: the default install makes `.claude/skills/bmad` a symlink; `--copy` makes no `.agents/`). `.agents/` is added to the template's `.gitignore` as well.
  - **`AGENT_SETUP.md`** reports each `open:` line.
- **The active initiative is behind the fence (2).** `bmad-architecture` needs `active_initiative` in `_bmad/custom/config.user.toml`; the agent may not write there, so the person had to step in mid-flow. The fence stays: a personal `*.user.toml` can override the team's rules (`review = "none"` would drop the review lenses). Instead, `RUNBOOK.md` "Plan the product" starts with step 0: the person writes the two lines. `doctor` reports it while it is missing.
- **Architecture decisions that the framework cannot do (4, 5, 6).** Four reviewers missed that no `spring.jackson.*` property makes a String field refuse a number (AD-18). Web search gave wrong latest versions and an artifact that is only a relocation POM. AD-10 gave work to the walking skeleton that a later story owns. `bmad-architecture.toml` now has four more facts:
  - pin versions only from Maven Central metadata and `npm view`;
  - check every setting, property or API an AD names against the pinned version (configuration metadata, Javadoc or a throwaway test), and say how;
  - name a rule's owner as "the story that first adds X";
  - an amended AD keeps its reason in the spine, because `.memlog.md` is not committed.

  It also has a fourth `finalize_reviewers` entry, appended to BMAD's two, that checks versions and named APIs.
- **The planning pull-request path (7, 11).** The tickets and scenarios must be on `main` before a lap, `main` takes only pull requests, and BMAD's board rules say never push. Changes:
  - `RUNBOOK.md` now says each planning step is a `planning/<step>` branch and pull request, with no ticket, judged like any other.
  - `bmad-agent-po.toml` lets the product owner push `planning/` branches and open their pull request.
  - Without Actions, the runbook says to run `judge.py --once` on planning pull requests and on `main` after a merge.
  - The lap's section C now judges `main` itself after a merge when Actions is off.
- **The walking skeleton (8, 9).** The skeleton never fits the fifteen-minute rule, and its review read 108 kB, mostly generated Spring, Angular and Playwright files. The blind reviewer's floor (`min(floor(sqrt(kB)+1), 10)`) then asked for 10 findings: 25 found, 14 rejected.
  - `bmad-agent-po.toml` exempts the skeleton from the size rule.
  - Generated starter files go in their own first commit (`starter:`). `bmad-build.toml` makes the plan do that, and writes the review diff from that commit, leaving out lockfiles, so the floor follows the hand-written size. BMAD's lenses are not forked.
- **A gated candidate that was not committed (10).** The local gates ran before `bmad-build` committed, so the candidate named the parent of the code tested.
  - Lap step A7 (both copies) now requires a clean tree before every gate run, and commits what `bmad-build` left.
  - `run-gates.sh`, when it names its own candidate (local runs only; CI and the judge always set one), warns about uncommitted changes and calls the candidate `<sha>-dirty-local`. No check is weaker; the identity check compares the same value as before.
- **Smaller items.**
  - `RUNBOOK.md` notes the npm 10 (Node 22 gates) and `packageManager: npm@11` mismatch.
  - `bmad-agent-po.toml` checks that containers have no story-only frontmatter (`id`, `tracker_id` on the repo store).
  - Not changed: whether to approve npm 11's install scripts (esbuild, lmdb). The pilot's build passes without them, and that is a decision for the owner.

Tested on Linux:
- `kit.py`: 35 tests, 12 new. They cover each open line with a stand-in for GitHub's answers, `gh_api` reading a stand-in `gh`, `--offline`, and that `sync` asks GitHub nothing.
- Harness tests pass: board 74, dispatch 53 (1 skipped), judge 53 (3 skipped), runtime 15. The two lap skills are identical.
- In a scratch project: `kit.py init`, then the new `--copy` install and `bmad setup` (BMAD `6.13.0-next`). `resolve_customization.py` merges all three changed TOML files (architecture 9 facts and 3 reviewers, build 10 facts, PO 13 facts). `doctor --offline` reports the missing initiative, and then nothing once it is set.

Not tested:
- `doctor` against real GitHub answers (the parsing is tested against a stand-in `gh`).
- Windows.
- A lap with the new facts.
- `calibrate.sh` (it needs a backend). The change to `run-gates.sh` only names the local candidate.

## 2026-11-23 — Dashboard: ticket no longer shows in "Needs you" during runtime verification

Seen: while `serve.py` reads plan files from the working tree, a ticket with `plan_status = "built"` (BMAD review just committed locally) appeared in the **"Needs you"** column with an "Open the pull request" hint for the entire duration of local gates + runtime verification — before the lap had pushed anything. The board could not tell a running lap from a stalled one.

- **`harness/board/board.py`, `_needs_you`:** moved the "Built → Open the pull request" prompt inside the `quiet_minutes is not None` branch. The prompt now fires only when the branch has gone quiet (lap stalled). An active "Built" branch returns `None` from `_needs_you`, so the ticket stays in the **Build** column while the lap runs gates and runtime verification.
- **`harness/board/dashboard.html`, `column()`:** removed `r.stage === 'Built'` from the "review" column check. With `needs_you` now `None` for an active "Built" ticket, it falls through to `return 'build'` instead of "review".
- **`harness/board/test_board.py`:** replaced `test_built_without_pull_request_asks_for_one` with two tests: one for the active case (running, Build column) and one for the quiet case (stalled, Open the pull request hint).

## 2026-11-22 — `kit.py`: one command installs the factory, one keeps it up to date (from `factory-pilot`)

Seen bringing `factory-pilot` up to the kit (factory-pilot#13, #14). 10 of 11 kit commits conflicted on cherry-pick, because a project's factory files were edited copies. The kit-only files and the fence had to be sorted out by hand. Real names had to be put back over placeholders. `RUNBOOK.md` and the two changelogs were merged by hand. 38 fenced files were staged for a human to copy. Design: [docs/superpowers/specs/2026-11-22-kit-sync-design.md](docs/superpowers/specs/2026-11-22-kit-sync-design.md) (#17), after coleam00/ai-software-factory's `template/` and `init`.

- **Layout:** the files the kit owns moved to `template/`, at the path a project has them. The files a project starts with and then owns moved to `seed/`:
  - `MISSION.md`;
  - `README.md` (was `PROJECT_README.md`);
  - the new `PROJECT_NOTES.md`;
  - `.github/CODEOWNERS`;
  - `.claude/launch.json`.

  The fenced settings left `fence/` for their real paths in `template/`. `init-project.sh` and `skills-lock.json` are gone; `skills-lock.json` is each project's own, written by BMAD.
- **`bin/kit.py`** (standard library), with 23 tests in `bin/test_kit.py`:
  - **`init --owner`** installs the factory in an empty repository and fills in the seeds' names.
  - **`status`** shows the kit commits a project lacks and the files it changed.
  - **`sync`** takes an update on a branch `factory/sync-<rev>`:
    - a file only the kit changed is replaced;
    - a file both sides changed goes to whichever change reached `main` later;
    - a file only the project changed is kept and listed while the kit is young;
    - the fence's deny lists are merged, so a project may add its own rules;
    - `.gitignore` lines are appended.

    It commits nothing and writes a pull request body. `--adopt <rev>` is the first sync of a project made before `kit.py`; `--discard <file>` takes the kit's version.
  - **`doctor`** checks that the fence denies every protected path and that the two lap skills match, and warns when `CODEOWNERS` misses a path.
- **`kit.lock.json`** in each project records the kit revision, a hash of each kit file (line endings normalised), and the kit's fence entries. It is now a protected path in all five places.
- **`bin/kit.json`** holds the kit's phase, `young` for now. Once `mature`, a change made in a project stops `sync` and fails `doctor`: every change then starts as an issue here.
- **No placeholders in the kit's files.** `RUNBOOK.md` uses "this repository", `gh browse` and `gh api repos/{owner}/{repo}`. Only the seeds keep `__OWNER__`, `__PROJECT__` and `__HOST__`, which `init` fills.
- **Documents:** `template/MODIFYING.md` describes the new flow, issue first. `template/RUNBOOK.md` setup uses `kit.py init` and points to `PROJECT_NOTES.md`. `AGENT_SETUP.md` starts from an empty repository and a kit clone. `README.md` describes the folders.
- **The kit's own agent files:** a root `AGENTS.md` (with `CLAUDE.md` importing it) is for agents changing the kit. It says everything in `template/` and `seed/` is product, not instructions. The root settings exclude those folders from `CLAUDE.md` loading (`claudeMdExcludes`) and deny the `lap` skill, which Claude Code would otherwise load from `template/.claude/skills/` once an agent touches files there.
- **CI:** the kit runs `.github/workflows/kit.yml`, with the `kit.py` tests, the harness tests and the lap-skill check. Its old workflows are now `template/.github/workflows/` and run only in projects.

Tested on Windows: `kit.py` 23 tests; harness tests board 73, dispatch 53 (1 skipped), judge 53, runtime 15. Not tested yet: `sync --adopt` on `factory-pilot` itself (its own pull request, the acceptance test); `kit.yml` on GitHub; whether `claudeMdExcludes` and the `Skill(template:lap)` deny keep the lap's rules away in a real session. The guards' `skip_template` stays for now, harmless once the kit is no longer a template repository.

## 2026-11-22 — The judge runs the gates with Git's bash on Windows (from `factory-pilot`, #12)

Seen validating the update from the kit in `factory-pilot`, on Windows 11 with Git for Windows. The judge started the gates as `bash`, and Windows finds a program started by name in System32 before it searches PATH. So it ran WSL's `bash.exe`, which exits 1 when no Linux distribution is installed. Every `gates` result was red. `classify.py` called that red `introduced`, so it would also have cost the lap a round. `shutil.which("bash")` alone does not fix it: on a usual Windows PATH, System32 comes before Git, and Git's installer often adds only `Git\cmd`, which has no bash.

- **`judge.py`:** new `find_bash()` skips the WSL and Microsoft Store stand-ins and falls back to the bash that ships with Git (found from `git` on PATH). With no bash at all, the gate log says `bash: command not found`, which `classify.py` already counts as the machine's.
- **`classify.py`:** the WSL "no installed distributions" message is a machine failure (`tool`).
- **`test_lap_round.py`:** runs `sys.executable`, not `python3`, which on Windows is often only the Store stand-in.

Tested on Windows: judge tests 53 (4 new), board 73 and dispatch 53 (1 skipped) all pass. Before the change, 3 failed. With a PATH of System32 and `Git\cmd` only, `which("bash")` finds WSL's and `find_bash()` finds Git's. Not tested on Linux; the change there is `which("bash")`, which finds the same bash as before.

## 2026-11-21 — Runtime verification: another agent checks the running app

Seen in planning topic 2: the gates prove that the tests the builder wrote pass, and Playwright's journeys are written by the same agent that builds the ticket. Nothing independent asked whether the running app does what the ticket says.

- **`harness/runtime/verify.py` and `verifier.md` (new, with tests):** after Archon's `archon-verify-runtime`, scripts around one agent step.
  - `start`: a fresh app with empty data, its build identity checked, a new and unique evidence folder, and the verifier's prompt.
  - A context-free subagent follows that prompt.
  - `check`: stops the app and judges the report:
    - every assertion is covered exactly once;
    - each one has exactly one non-empty evidence file inside the attempt's folder;
    - the identity matches the build under test;
    - nothing was written into the checkout.
  - The result is `verified`, `failed` (a `runtime` round), `inconclusive` (no round, a human looks) or `malformed` (one fresh attempt, with the reason, then `inconclusive`).
- **The scenario** is `docs/runtime/<ref>.json`, one assertion per acceptance criterion.
  - `bmad-agent-po.toml` has the product owner write it at planning, committed to `main` before the lap.
  - `verify.py` reads it from `origin/main` and refuses a branch whose copy differs. That is the `pull_request_target` idea: the change cannot edit what judges it.
  - `bmad-build.toml` tells the builder not to touch it. No scenario, or no backend yet, is `skipped`, and the pull request says so.
- **`lap` skill (both copies), step 7:** runtime verification after green gates. The subagent gets the prompt path and nothing else. A `failed` result takes a round and goes back to the gates. The pull request carries `verify.py <ref> summary`, and so does the template.

Lessons kept from Archon:
1. An agent's report is checked by a script, never trusted.
2. Evidence is raw tool output saved by the tool, one file per assertion, inside a fresh folder per attempt.
3. A malformed report gets one fresh attempt with the checker's reason, never the earlier observations.
4. The verifier writes nothing in the checkout. The prompt says to start every command with `cd` to the attempt folder, and the checker compares `git status` before and after.
5. Identity is probed from the running app, not taken from Git.

Tested: 15 tests in `harness/runtime`, with a stand-in app that keeps the runtime contract, real Git and a scripted verifier:
- verified, failed, inconclusive, and malformed-then-retried;
- evidence outside the folder, or empty;
- the build identity disagreeing;
- a stray file in the checkout;
- the scenario changed on the branch, or only on the branch;
- skipped;
- an app that does not start, and one that reports another build.

Not tested yet: a real Spring app with a real subagent as the verifier. Still open: running it in CI or the factory judge, and making it a required check.

## 2026-11-21 — Why the gates are red: the change, main, or the machine

Seen in planning topic 2, and in Archon's incident log (2026-10-25): an attempt cap that counted a broken toolchain against the work parked good tickets as `needs-owner`. The round budget had the same gap. Every red gate looked like the change's fault, so a lost network or a red `main` spent a lap's rounds, and the dispatcher started fix rounds that could not succeed.

- **`harness/judge/classify.py` (new, with tests):** after `archon-validate`'s classify step. It says why red gates are red:
  - `environment`: a known machine failure is in the log (network, port in use, missing tool, full disk, browser install);
  - `inherited`: with `--check-main`, the gates run on `origin/main` alone and are red there too;
  - `timeout`;
  - otherwise `introduced`, the conservative default.

  A machine failure needs positive evidence, and the patterns are kept narrow. `ECONNREFUSED` is left out on purpose: the app under test may have crashed.
- **`harness/judge/judge.py`:** classifies every red `gates`.
  - An `inherited` red is posted red, beginning "Not this change:". To decide, the judge judges `main` alone once and reuses that verdict.
  - A machine failure runs again on the next pass. The same commit failing on the machine twice is posted `error`, "Not this change: the machine failed twice", and is not run again until `--retry-errors`. That is Archon's "the same fault twice stops, it does not keep spending".
  - Neither counts against the round budget. The judge's comment states the cause and its evidence.
- **Board and dispatcher:** the board keeps each check's description. The dispatcher starts no fix round for a red that begins "Not this change:"; it goes to the human.
- **`lap` skill (both copies):**
  - step A7 saves the gates log and asks `classify.py --check-main` before taking a round;
  - steps A10 and B take no round for "Not this change";
  - the budget rule says the agent never decides the cause itself.

Tested: 49 judge tests, 7 of them new:
- machine-failure lines classified as `environment`, and lines the change can cause classified as `introduced`;
- a machine failure runs again, then stops;
- `--retry-errors` judges again;
- an `inherited` red takes no round;
- an `introduced` red takes one, and `main`'s verdict is reused.

One new dispatcher test: no fix round for "Not this change". One real `classify.py --check-main` run on this kit. Not tested yet: a real project's logs (network failures in Maven or npm as they really print). Still open: runtime verification, part 2 of topic 2.

## 2026-11-21 — One round budget per lap, for every check

Seen in planning: each loop had its own limit of 3, and `bmad-build`'s review loopback had BMAD's own 5. Together a lap could spend 3 review loopbacks, 3 local gate fixes, 3 CI fixes and any number of "main moved" rounds, and runtime verification would add another loop. Separate limits add up; the cost the person wanted bounded did not have a bound.

- **`harness/rounds.json` (new):** one budget, 3 rounds per lap, shared by five sources: `review`, `gates`, `runtime`, `ci`, `main-moved`. A round is a fix that is checked again.
- **`harness/board/lap_round.py` (new, with tests):** `take` records a round in `.lap/<ref>.jsonl`, next to the lap's signals, or refuses it. `status` shows the count. `grant` is the human's way to add rounds.
- **`lap` skill (both copies):** one rule for every loop, in place of the separate limits in A7, B and D. A machine failure takes no round. Fix the whole class of a finding in one round. The pull request states the rounds used.
- **`_bmad/custom/bmad-build.toml`:** review loopbacks take a `review` round instead of counting to BMAD's 5; patches in the same pass take none.
- **Dispatcher:** shares the budget with the lap's own record, using whichever count is higher. A human grant gives a dispatched lap more rounds. New: a lap that falls behind `main` 3 times stops (`MAX_MOVED_ROUNDS`).
- **Board:** the middle review number is rounds used; the live board's ticket shows each round.
- **Fence:** the agent may not `grant` rounds, nor edit `.lap/*.jsonl`.
- **`.github/pull_request_template.md`:** "Fix rounds so far" becomes "Rounds used".

Lessons taken from the Archon SDLC pack (`deliver/scripts/round.ts`, `review-synthesize.md`, `docs/incidents.md` in `coleam00/ai-software-factory`):

1. **A script counts, not the agent,** and the cap ends a lap with a reason (as Archon's `round_cap`) instead of an error.
2. **Infrastructure failures are not attempts.** In Archon (2026-10-25), an attempt cap counted a broken Bun as the work's failure and parked good work as `needs-owner`. Here a machine failure is a `manual-step` stop, never a round.
3. **Reported is not stopped.** Archon's manager wrote a fault down while the loop kept spending all night. Here `take` itself records the stop, so the board and dispatcher see it even if the agent ignores the output.
4. **The same finding twice stops early,** as Archon's "same fault twice in a row stops launches" and its review rule against "one nearby symptom per round".
5. **Counted across every park and unpark,** as Archon's manager counts attempts. A `release` or a new session does not reset the budget; only a recorded human grant adds to it.

After pull request #8 merged, the factory judge brakes too:

- **`harness/judge/judge.py`:** counts each pull request's red `gates` runs; a timeout does not count. Once they reach the budget, it judges no new commit and posts `gates` red, "Round budget spent". The label `human-granted-round` gives one more round each time a human adds it, read from the pull request's events. This is the brake outside the agent for laps run by hand, and it holds when a lap's own record is lost.
- **Lap step A10** takes a `ci` round before fixing a red `gates` from the judge, and stops on "Round budget spent". **Setup** creates the third label.

Tested: 42 judge tests, 4 new (the brake, a grant by label, a timeout does not count, each pull request has its own count); 73 board tests, 8 of them new for the budget; 50 dispatcher tests, 4 new (the lap's rounds share the budget, deleting the record buys nothing, a grant adds a round, the main-moved brake). `bmad-build.toml` parses. Not tested yet: a real lap, and a BMAD review loopback calling `take`. Still open: the judge counts only red `gates` runs, not the lap's review and local gate rounds, which it cannot see. It cannot yet tell a red caused by the change from one caused by the machine; sorting the cause is planned with runtime verification.
## 2026-11-21 — The lap runs the judge, and hands over a judged pull request

Seen in review of the entry below: a lap run by hand ended with a command for the person to type. The factory's job is a pull request that is ready to merge, so the person had become the CI again.

- **`lap` skill (both copies), new step A10:** without Actions, the lap runs `harness/judge/judge.py --once --pr <n>` on its own pull request. A red `gates` is a fix round, followed by the judge again, within the 3 fix rounds. A red guard stops for the human's label. A conflict goes to section D. A judge that cannot run stops with `waiting manual-step` and is not a round. A green result is handed over as ready to merge. Section B runs the judge again after each fix. A dispatched lap skips the step, since it has no token.
- **Fence (`fence/claude-settings.json`, `fence/kiro-factory.json`):** an agent may not post a commit status itself (`gh api …statuses…`). The judge posts from its own process, which the fence does not cover.
- **`harness/judge/judge.py`:** writes `.factory/.gitignore` before its first worktree, so a lap's tree stays clean while the judge runs in it.
- **`RUNBOOK.md`:** the on-demand way is now the lap's own last step.

Why the lap may run its own judge: it cannot change what the judge checks (`harness/` is fenced and taken from `main`), and posting a status by hand is fenced. A faked status was possible before this change too; branch protection and the human's review remain the last word.

Tested: 38 tests in `harness/judge`, including a clean `git status` after a real gate run. Not tested yet: a real lap through step A10.

## 2026-11-21 — The judge on demand, for laps run by hand

Seen while planning the judge for `my-factory-demo`: the person runs laps by saying "run a lap", not with the dispatcher, so a judge that has to keep running did not fit.

- **`harness/judge/judge.py`:** `--pr <n>` judges one pull request (both guards and the gates; not `main`). `--once` now judges everything waiting and then exits; before, it ran one gate. `--once --pr <n>` prints the three results in one line and exits 0 only when all three are green.
- **`lap` skill (both copies):** step A9, without Actions, tells the user the exact judge command for the new pull request. The lap does not run the judge itself, so it never judges its own work. Section B reads a red `gates` from the judge's comment.
- **`RUNBOOK.md`, "Without GitHub Actions":** leads with the on-demand way for laps run by hand, then the always-on way for the dispatcher.

Tested: 37 tests in `harness/judge` (one pull request only, red is not ready, a pull request that is not open, `--once` judges everything and stops); a dry run against this kit.

## 2026-11-21 — The gates run without GitHub Actions

Seen in `my-factory-demo`, and left open by the entry below: without Actions, `gates` was the person's own run of `run-gates.sh` before each merge. Nothing stopped a merge they had not checked, and a fix round had no failing output to read.

- **`harness/judge/judge.py`** also judges `gates`. It runs `run-gates.sh` on each open pull request merged with `main`, in a worktree of its own clone, and then on `main` itself after each merge.
  - `harness/` is taken from `main`, so a pull request cannot change the gate that judges it.
  - The gate runs with no GitHub token in its environment, under a 30-minute limit that kills its whole process tree. The lap-skill copy check from `gates.yml` is included.
  - One run per pass, oldest pull request first; each commit is judged once. Verdicts are kept in `.factory/judge/verdicts.json`, so a status that disagrees with a verdict is overwritten without running again.
  - A red gate's log tail goes into one pull request comment, edited in place.
  - A pull request that conflicts with `main` gets no status; it waits for a "main moved" round.
  - New flags: `--no-gates`, `--port` (default 8190) and `--gates-timeout`.
- **`harness/dispatch/dispatch.py`:** with no check run to read, a fix round reads the judge's comment for that commit.
- **`RUNBOOK.md`, "Without GitHub Actions"** is rewritten around the judge: its own clone, what its machine needs, its token, and requiring all three statuses once it runs. **`AGENT_SETUP.md`** and **`harness/README.md`** point to it.

Tested: 33 tests in `harness/judge`. Six of them run real Git against a local origin: the merge, the harness restored from `main`, no token reaching the gate, the lap-skill check, a conflict, and the timeout kill. Two dispatcher tests cover reading the comment. The board and dispatcher suites still pass, and one real gate run on this kit's `main` passed (no backend: notice only). Not tested yet: a real Spring and Angular project's gates through the judge; posting on GitHub Enterprise. Still open: trusting only the judge's own statuses; running the judge on a shared machine; `calibrate` and the board rebuild through the judge.

## 2026-11-21 — The guards run without GitHub Actions

Seen in `my-factory-demo` (see the 2026-11-20 entry): where Actions is not allowed, `protected-paths` and `scope-guard` never ran. The only guard was a person reading changed files against two regexes inside a workflow file.

- **`harness/judge/guards.json` and `guards.py` (new):** the two guards' patterns and logic in one place, with tests. `judge-guards.yml` checks out only `harness/judge/` from the base branch and calls `guards.py`, so it still runs no pull request code. The pattern no longer lives in the workflow.
- **`harness/judge/judge.py` (new, with tests):** the factory judge. It polls the open pull requests and posts both guards as commit statuses, judged by the same `guards.py`, only when a status changes. `--once`, `--dry-run`, `--interval`. The board, dispatcher and branch protection already read commit statuses.
- **`RUNBOOK.md`, "Without GitHub Actions":** start the judge and require the two statuses in branch protection. **`MODIFYING.md`:** the protected-path pattern's fifth place is now `guards.json`.

Tested: 16 unit tests in `harness/judge`, including one that pins the workflow to `guards.py`; the board and dispatcher tests still pass; a dry run against this kit (no open pull requests). Not tested yet: the workflow on GitHub; posting a real status on GitHub Enterprise. Still open: the judge does not run `gates` or `calibrate`, and does not yet trust only its own statuses.

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
