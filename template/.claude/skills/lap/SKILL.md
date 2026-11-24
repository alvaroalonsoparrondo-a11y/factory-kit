---
name: lap
description: 'Runs one factory lap: takes exactly one ticket from the BMAD board through build, review and local gates, pushes a branch and opens its pull request for a human to merge. Use when the user says "run a lap", "lap <ticket id>", "next ticket", pastes a failing check from a lap pull request, or says a lap pull request was merged.'
---

# Lap

One ticket, one branch, one pull request. You build; CI judges; a human merges. Follow the steps in order. Never skip one.

**Every lap runs in its own git worktree**, `<lap tree>` below: `../<project>-wt/story-<ticket-id>`, next to the main checkout, where `<project>` is the main checkout's folder name (the first path `git worktree list` prints). The main checkout is never switched off `main`, so the human prepares the next tickets there while laps run, and the live dashboard follows each lap in its worktree. The lap makes the worktree in step A4 and removes it when the lap ends (sections C and E). Wherever the session was opened, run every command of the lap inside `<lap tree>`: `cd <lap tree>` at the start of each shell command, or `git -C <lap tree>`, and give file tools paths inside it. To find `<lap tree>` for a later round, take the path `git worktree list` shows for `story/<ticket-id>`. The gate port (`<port>` below) is the one the user gave; otherwise `PORT` from the environment when it is set (the dispatcher sets it); otherwise 8081, so the lap's gates never collide with an app the human runs on 8080.

**A dispatched lap.** The dispatcher (`harness/dispatch/dispatch.py`) may have claimed the ticket already: `story/<ticket-id>` exists on `origin` and is checked out in this worktree. Then, in section A, skip step 2 (the ticket is the one named), and in step 4 do not create the branch: check that it matches `origin/story/<ticket-id>` and go on. When `FACTORY_DISPATCHED=1` is set, the lap runs headless and nobody can answer: wherever this skill or `bmad-build` would ask, confirm or wait, signal `waiting` (below) and end instead; the dispatcher shows the signal to the human. The dispatcher starts the fix rounds (B) and "main moved" rounds (D) itself, with the failing check in the prompt, and does section C after the merge.

Hard rules for the whole lap (from `FACTORY_RULES.md`):

- Never change a factory file during a lap. Never weaken a test.
- Open the lap's pull request with `gh`. Never label, approve or merge a pull request; a human merges.
- If you cannot finish within the limits below, stop and report. A stopped lap is a correct result.
- **One round budget for the whole lap.** A round is a fix that is checked again: a review loopback in `bmad-build`, a red local gate fixed and run again, a failed runtime check, a red check on the pull request, a merge of `main` that needed conflicts resolved. Every source shares one budget, 3 rounds per lap (`harness/rounds.json`). Before every such fix, run `python harness/board/lap_round.py <ticket-id> take <source> "<what the check found>"`, with `<source>` one of `review`, `gates`, `runtime`, `ci`, `main-moved`.
  - Exit 0: make the fix. Fix the whole class of the finding in this round (every place the same cause shows), not the one instance the check named.
  - Any other exit: stop the lap, not only this check: do not move on to another check or step. The script has already signalled the stop, and every later `take` refuses too until a human grants a round; report its output. Never change code for a finding without a round, and never run `lap_round.py … grant`: only a human gives more rounds.
  - Not a round: the first run of any check, a clean merge of `main`, a failure of the machine rather than the change (a usage limit, a check that could not start, a lost network, a missing tool), and a red that `main` has alone, too. Those take no round: signal `waiting manual-step` (the machine) or `waiting decision` (`main` is red) and stop. For red gates, `harness/judge/classify.py` says which it is (step A7); do not decide it yourself.
- **Say when you wait.** Before you stop to wait for the human, for any reason, run `python harness/board/lap_signal.py <ticket-id> waiting <kind> "<what you need>"`. When the human has answered, run `python harness/board/lap_signal.py <ticket-id> working` before you go on. This includes stops inside `bmad-build` (a permission, a choice, approving the plan) and the limits below. The kind is one of `permission`, `choice`, `approval`, `question`, `manual-step`, `limit`, `decision`. The final hand-over in step A9 needs no signal; the pull request shows it. You may run `lap_signal.py`; never change it. A prepared ticket's lap (step 3) never waits about what the ticket should do: it hands the ticket back instead (section E).

## A. New lap

1. **Check the start state.** Run `git fetch origin`. The main checkout's state does not matter: the lap never works in it. If `story/<ticket-id>` already has a worktree (`git worktree list`) and this is not a dispatched lap, a lap for this ticket is already running: stop and say where.
2. **Pick the ticket.** Use the id the user gave. If they gave none, ask the product owner skill (`bmad-agent-po`, BOARD) for the next ready ticket in build order and confirm it with the user in one line.
3. **Read** `MISSION.md`, `FACTORY_RULES.md`, `harness/README.md` and the ticket, in full. Then read the ticket's triage: `python harness/board/triage.py <ticket-id> check`. Its first line is `none`, `stale <route>: <why>` or `fresh <route>`.
   - `fresh ready-to-implement` and `prepared: <leaf path>`: the ticket is **prepared**. The human approved its "what" ahead, in that leaf file. The plan is yours to approve in step 6, and nothing about the ticket's intent may wait for the human in this lap: where it would, hand back (section E). Read the leaf file in full.
   - `fresh ready-to-implement` and `plan: the lap approves it`: the plan is yours to approve in step 6.
   - `stale ready-to-implement`, `stale ready-to-spec` or `none`, and the ticket's leaf file says `refined: true`, in a lap a human started: the human prepared it, and only the triage is out of date. Triage it again yourself: follow the `triage` skill for this ticket (it only reads), as of `origin/main`. If its answer is `ready-to-implement`, show its summary and ask in one line whether to record it (signal `waiting approval "record the new triage of <ticket-id>"`). On a yes, save the answer to `.lap/<ticket-id>-triage.json`, run `python harness/board/triage.py <ticket-id> record .lap/<ticket-id>-triage.json --push`, signal `working`, and run `check` again: it now says `prepared:`. On a no, or any other answer, go on as below.
   - Anything else: a human approves the plan, as always. A dispatched lap only starts on a fresh `ready-to-implement`, so there `main` moved under it: signal `waiting decision "triage: <the first line>"` and stop.
4. **Branch, in the lap's worktree.** `git worktree add -b story/<ticket-id> <lap tree> origin/main`. If the main checkout has `_bmad/custom/config.user.toml` (the human's, never committed), copy it to the same path in `<lap tree>`, unchanged: BMAD's scripts there need its active initiative, and `bmad-build`'s `tickets.py find` fails without it. Then, in `<lap tree>`, `git push -u origin story/<ticket-id>` at once. From here on, work only in `<lap tree>`. Tell the user in one line where it is, as an absolute path: `Lap <ticket-id> works in <path>`. The live dashboard now shows the lap as started, with its worktree. The first gate run in a new worktree is slow: it fills its own `node_modules` and `backend/target`.
5. **Irreversible check.** If the ticket needs anything in `FACTORY_RULES.md` section 1 or a protected path, stop. Do not build a partial version. Make the stop visible on the board: ask the product owner skill (`bmad-agent-po`, BOARD) to mark the ticket blocked with the rule as the reason (`tickets.py mark <ref> draft --blocked "<rule and why>"`), commit, `git push`. Then tell the user which rule applies.
6. **Build with BMAD.** Invoke the `bmad-build` skill with the ticket, and tell it that the project root is `<lap tree>`: every file it reads or writes, the plan included, and every BMAD script it runs (`--project-root <lap tree>`) are there, never in the main checkout. Follow its workflow fully, including its review step. It commits locally. It must not push. One push is yours: when the plan is approved, commit the plan file if `bmad-build` has not, and `git push`, so the board shows the ticket as building. Then let `bmad-build` continue. Each of its review loopbacks takes a round first (source `review`); `_bmad/custom/bmad-build.toml` tells it so, and when `take` refuses, `bmad-build` halts and the lap stops.
   - **A prepared ticket** (step 3 printed `prepared:`): tell `bmad-build` the ticket is prepared and name the leaf file. Its plan's `<frozen-after-approval>` block carries the leaf's numbered criteria and its Boundaries word for word, under `## Acceptance (from <leaf path>)`, beside the Intent `bmad-build` writes. At CHECKPOINT 1, re-read the plan. With no `## Open Questions`, choose **Approve and continue**, whatever the ticket's `risk`, and put `Plan approved by prepared ticket (<leaf path>)` in the plan's commit message. With any open question, hand back (section E) instead of asking. Later in the lap, an `intent_gap` from review, or any other question about what the ticket should do, also hands back. A stop that is not about the ticket's intent (the machine, a usage limit, the round budget) is signalled as everywhere else.
   - **Approving the plan yourself**, only when step 3 said the lap approves it: at `bmad-build`'s CHECKPOINT 1, re-read the plan. If it has no `## Open Questions` and its frozen Intent says what the triage summary says, choose **Approve and continue**, and put `Plan approved by triage (docs/triage/<ticket-id>.json)` in the plan's commit message. If it has open questions, or its intent differs, the triage was wrong: stop and wait for the human as at any checkpoint (signal `waiting approval`, with the questions).
7. **Local gates.** First, everything is committed: `git status --porcelain` must print nothing, so the candidate the gates print is the commit they tested. If `bmad-build` left changes (its last step commits them; review patches come before it), commit them now with the plan's title. Then run `PORT=<port> bash harness/run-gates.sh > .lap/<ticket-id>-gates.log 2>&1`, and read its exit status and the log. Do the same before every later run of the gates in this lap.
   - Green (exit 0): go on.
   - Red: ask why, never guess: `python harness/judge/classify.py .lap/<ticket-id>-gates.log --check-main --port <port + 100>`. It prints one word first:
     - `introduced`: the change caused it. Take a round (`take gates "<the failing check and line>"`), fix the cause in application or test code, run the gates again.
     - `environment`: the machine failed (a download, a port in use, a missing tool). No round: signal `waiting manual-step "<its evidence line>"` and stop.
     - `inherited`: the gates are red on `origin/main` alone, too. No round: signal `waiting decision "main is red: <its evidence>"` and stop.
     - `timeout`: no round on its own. Look at the log for a hang the change caused; if there is one, it is `introduced`; if not, signal `waiting manual-step` and stop.
   - **Then, runtime verification**, once the gates are green. A separate agent with no context exercises the running app against the ticket's scenario (`docs/runtime/<ticket-id>.json`, written by the product owner and read from `main`), and a script judges its evidence:
     1. `python harness/runtime/verify.py <ticket-id> start --port <port>`. `skipped` (no scenario, or no backend yet): go on, and say so in the pull request. `started`: its second line is the verifier's prompt. Exit 2 (the scenario on the branch differs from `main`, or is not on `main`): restore it from `main` or stop and say so; never change it. Anything else, or `inconclusive`: no round; signal `waiting manual-step "<its reason>"` and stop.
     2. Launch a context-free subagent with exactly this prompt: `Read <the prompt path> with your Read tool and follow it exactly.` Give it nothing else: not the plan, the diff, the ticket or your opinion. If your agent cannot launch a subagent, run `verify.py <ticket-id> stop`, signal `waiting manual-step "runtime verification needs a subagent"` and stop.
     3. `python harness/runtime/verify.py <ticket-id> check`. It prints one word first:
        - `verified`: go on.
        - `malformed`: the verifier broke the report's rules. Go back to 1 once; the script gives it the reason and counts the attempts.
        - `failed`: the app does not do what the scenario says. Take a round (`take runtime "<the failed assertions and what was observed>"`), fix the application, then run the gates again from the top of this step, and runtime verification after them.
        - `inconclusive`: something could not be judged. No round: signal `waiting decision "<its reason>"` and stop.
     4. Never run the verifier's checks yourself instead, and never edit its report or evidence.
8. **Push.** `git fetch origin`. If `origin/main` has moved since the branch was cut, do section D first. Then `git push`. Nothing else.
9. **Hand over.** Write the pull request text to `.lap/<ticket-id>-pr.md`. Git ignores `.lap/`; never commit it.
   - First line: the title, `<ticket-id>: <ticket title>`. Then one blank line.
   - Then the body, filling in every part of `.github/pull_request_template.md`: the ticket, what changed, the local gate result with the candidate id it printed, the runtime verification result (`python harness/runtime/verify.py <ticket-id> summary`), the triage route and who approved the plan, the rounds used (`lap_round.py <ticket-id> status`), each assumption made on an open question in `MISSION.md`, and anything deferred.

   Open the pull request from that file: `gh pr create --base main --head story/<ticket-id> --title "<title>" --body-file <a copy of the file without its first two lines>`. Print the pull request's URL.

   If `gh` fails, print its error, the path of the file, and a link that opens the pull request form already filled in: `https://<host>/<owner>/<repo>/compare/main...story/<ticket-id>?expand=1&title=<title>&body=<body>`, with the title and body URL-encoded (take host, owner and repo from `git remote get-url origin`; the host is `github.com` or a GitHub Enterprise host). If that link would be longer than 8000 characters, print it without `title` and `body` and say to paste them from the file.

   With GitHub Actions, stop here: CI judges the pull request, and the lap waits for CI and the human. Without it (`gh api repos/<owner>/<repo>/actions/permissions` shows `"enabled": false`), nothing judges it yet: go on to step 10.

10. **Judge (only without GitHub Actions).** Run the factory judge on the pull request: `python harness/judge/judge.py --once --pr <number> --port <port + 100>`. It posts the three checks as commit statuses, from `harness/` on `main`, and prints one line with the results. Never post a status any other way.
    - Exit 0, all three green: tell the user the pull request is ready for their review and merge, with its URL and the judge's line. Stop.
    - `gates` red, and its description does not start with "Not this change": do a fix round (section B) with the judge's comment as the failure. It takes a `ci` round first, and when `take` refuses, the lap stops there. Then run the judge again.
    - `gates` red or `error` starting with "Not this change": the judge found the cause outside the change (its comment says `environment` or `inherited`, with the evidence). No round: signal `waiting manual-step` (the machine) or `waiting decision` (`main` is red) with that evidence, and stop.
    - `gates` red with "Round budget spent": the judge will not judge another commit. Stop and signal `waiting limit "round budget spent on the pull request"`; only a human grants a round.
    - `protected-paths` or `scope-guard` red: section B, rule 2. If the change is needed, stop and signal `waiting decision "<check>: <the paths>"`; the label is the human's call.
    - No `gates` result, because the branch conflicts with `main`: do section D, then run the judge again.
    - The judge itself fails (no Java, no network, port taken): signal `waiting manual-step "<its error>"` and stop. It is not a fix round.

    A dispatched lap skips this step: it has no GitHub token, so the dispatcher's human runs the judge.

## B. Fix round (the user pastes a failing check)

1. Work in the lap's worktree: the path `git worktree list` shows for `story/<ticket-id>`. If there is none, make it from the pushed branch: `git fetch origin && git worktree add <lap tree> story/<ticket-id>`.
2. Read the failure. Without GitHub Actions, a red `gates` from the factory judge has its last log lines in the judge's comment on the pull request (it starts with `<!-- factory-judge:gates -->`); when the user only says the check is red, read that comment with `gh api repos/<owner>/<repo>/issues/<number>/comments`.
   - `gates`: if the failure says "Not this change" (the judge's cause is `environment` or `inherited`), take no round: signal as in step A10 and stop. Otherwise reproduce as in step A7, which also asks `classify.py` why; fix and run again until green.
   - `protected-paths` or `scope-guard`: you changed something you may not change. Revert that part. If the ticket cannot be done without it, stop and say so.
3. Commit and `git push`. Tell the user in one line what you changed. Without GitHub Actions, then run the judge again (step A10).
4. Every fix here takes a round first: source `ci` (step 2, `gates`). A guard needs no round: reverting a change you may not make is not a fix that is checked again. When `take` refuses, stop and recommend that the product owner split or rewrite the ticket, with the findings it printed.

## C. After the merge (the user says it merged)

A dispatched lap skips this section: the dispatcher marks the ticket done on `main`, removes the worktree and writes the lap report.

1. Get onto the merged `main`, in the lap's worktree: `main` is checked out in the main checkout, so `git fetch origin && git switch --detach origin/main` in `<lap tree>`.
2. Ask the product owner skill (`bmad-agent-po`, BOARD) to mark the ticket done, and commit it.
   - `git push origin HEAD:main`. If it is refused because `main` moved, `git fetch origin && git rebase origin/main` (one local commit, not yet pushed) and push again. Never force-push.
   - Without GitHub Actions (`"enabled": false`, as in step A9): nothing judges the new `main` by itself. Run `python harness/judge/judge.py --once --port <port + 100>`, which judges `main` after the merge, and include its line in the report below. If it fails or `main` is red, say so in the report; do not fix it in this lap.
3. Report one line: ticket, rounds used (`python harness/board/lap_round.py <ticket-id> status`), which checks had failed on the way.
4. Remove the lap's worktree, from the main checkout: `git worktree remove <lap tree>`, then `git branch -D story/<ticket-id>` (the merged branch; the pull request keeps its history). If `git worktree remove` refuses because of untracked files, they are build output (`node_modules`, `target`): use `--force`. If the session itself was opened inside `<lap tree>` (an older hand-started worktree), say the worktree can be removed instead; in the Claude desktop app, archiving the session does it.

## D. Main moved (the branch is behind `origin/main`)

Run this when step 8 finds `origin/main` ahead, when the user says main moved, or when the pull request shows a conflict or is out of date.

1. `git fetch origin && git merge origin/main`. Merge, never rebase: the branch is pushed and force-push is not allowed.
2. Conflicts: resolve them in application and test code only, keeping both changes' behaviour. If a conflict is in a factory file or cannot be resolved without changing what the other change does, stop and report.
3. Run `PORT=<port> bash harness/run-gates.sh` until green, then `git push`. CI judges the merged result again.
4. A clean merge with no conflict takes no round. Before you resolve a conflict, or change code to get the gates green after the merge, take a round: source `main-moved`. Tell the user in one line what came in from `main` and what you reconciled.

## E. Hand back (prepared tickets only)

A prepared ticket's lap never waits for the human about what the ticket should do. When it would (an open question in the plan, an `intent_gap` from review, any question about the intent), it gives the ticket back and ends. The human answers in planning time; the ticket is then triaged and built again. A hand-back takes no round, and never comes with a pull request.

1. Write the questions down, one line each, as the human must answer them in the ticket.
2. Mark the ticket blocked on `main`, from a throwaway worktree so this lap's branch is not touched:
   - `git fetch origin`, then `git worktree add --detach <tmp> origin/main`.
   - In `<tmp>`: ask the product owner skill (`bmad-agent-po`, BOARD) to mark it, `tickets.py mark <ref> draft --blocked "Handed back by the lap: <the questions, joined with '; '>"`, then commit `Hand back ticket <ticket-id>: <the first question>`.
   - `git push origin HEAD:main`. If it is refused because `main` moved, `git fetch origin && git rebase origin/main` (one local commit) and push again. Never force-push.
   - `git worktree remove --force <tmp>`.
3. Delete the lap's branch on `origin`: `git push origin --delete story/<ticket-id>`. Its plan and code go with it; the next lap starts fresh.
4. Report one line: `Handed back <ticket-id>: <the questions>`. Run no `lap_signal.py waiting`: nothing waits. A dispatched lap leaves its worktree: the dispatcher removes it. A hand-started lap removes its own, as in step C4.
