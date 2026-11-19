---
name: lap
description: 'Runs one factory lap: takes exactly one ticket from the BMAD board through build, review and local gates, pushes a branch and opens its pull request for a human to merge. Use when the user says "run a lap", "lap <ticket id>", "next ticket", pastes a failing check from a lap pull request, or says a lap pull request was merged.'
---

# Lap

One ticket, one branch, one pull request. You build; CI judges; a human merges. Follow the steps in order. Never skip one.

A lap runs in the main checkout or in a git worktree, so the human can keep working in the main checkout while a big lap runs. You are in a worktree when `git rev-parse --git-dir` differs from `git rev-parse --git-common-dir`. The gate port (`<port>` below) is the one the user gave; otherwise `PORT` from the environment when it is set (the dispatcher sets it); otherwise 8080 in the main checkout and 8081 in a worktree, so the lap's gates never collide with an app the human runs.

**A dispatched lap.** The dispatcher (`harness/dispatch/dispatch.py`) may have claimed the ticket already: `story/<ticket-id>` exists on `origin` and is checked out in this worktree. Then, in section A, skip step 2 (the ticket is the one named), and in step 4 do not create the branch: check that it matches `origin/story/<ticket-id>` and go on. When `FACTORY_DISPATCHED=1` is set, the lap runs headless and nobody can answer: wherever this skill or `bmad-build` would ask, confirm or wait, signal `waiting` (below) and end instead; the dispatcher shows the signal to the human. The dispatcher starts the fix rounds (B) and "main moved" rounds (D) itself, with the failing check in the prompt, and does section C after the merge.

Hard rules for the whole lap (from `FACTORY_RULES.md`):

- Never change a factory file during a lap. Never weaken a test.
- Open the lap's pull request with `gh`. Never label, approve or merge a pull request; a human merges.
- If you cannot finish within the limits below, stop and report. A stopped lap is a correct result.
- **Say when you wait.** Before you stop to wait for the human, for any reason, run `python harness/board/lap_signal.py <ticket-id> waiting <kind> "<what you need>"`. When the human has answered, run `python harness/board/lap_signal.py <ticket-id> working` before you go on. This includes stops inside `bmad-build` (a permission, a choice, approving the plan) and the limits below. The kind is one of `permission`, `choice`, `approval`, `question`, `manual-step`, `limit`, `decision`. The final hand-over in step A9 needs no signal; the pull request shows it. You may run `lap_signal.py`; never change it.

## A. New lap

1. **Check the start state.** `git status` must be clean. Run `git fetch origin`. You need not be on `main`: the lap branches from `origin/main` wherever it runs. If the tree is not clean, stop and say what is in the way.
2. **Pick the ticket.** Use the id the user gave. If they gave none, ask the product owner skill (`bmad-agent-po`, BOARD) for the next ready ticket in build order and confirm it with the user in one line.
3. **Read** `MISSION.md`, `FACTORY_RULES.md`, `harness/README.md` and the ticket, in full.
4. **Branch.** `git switch -c story/<ticket-id> origin/main`, then `git push -u origin story/<ticket-id>` at once. The board now shows the lap as started.
5. **Irreversible check.** If the ticket needs anything in `FACTORY_RULES.md` section 1 or a protected path, stop. Do not build a partial version. Make the stop visible on the board: ask the product owner skill (`bmad-agent-po`, BOARD) to mark the ticket blocked with the rule as the reason (`tickets.py mark <ref> draft --blocked "<rule and why>"`), commit, `git push`. Then tell the user which rule applies.
6. **Build with BMAD.** Invoke the `bmad-build` skill with the ticket. Follow its workflow fully, including its review step. It commits locally. It must not push. One push is yours: when the plan is approved, commit the plan file if `bmad-build` has not, and `git push`, so the board shows the ticket as building. Then let `bmad-build` continue.
7. **Local gates.** Run `PORT=<port> bash harness/run-gates.sh`.
   - Green: go on.
   - Red: fix the cause in application or test code and run again. At most **3** fix rounds. Still red after 3: stop and report the failing output.
8. **Push.** `git fetch origin`. If `origin/main` has moved since the branch was cut, do section D first. Then `git push`. Nothing else.
9. **Hand over.** Write the pull request text to `.lap/<ticket-id>-pr.md`. Git ignores `.lap/`; never commit it.
   - First line: the title, `<ticket-id>: <ticket title>`. Then one blank line.
   - Then the body, filling in every part of `.github/pull_request_template.md`: the ticket, what changed, the local gate result with the candidate id it printed, each assumption made on an open question in `MISSION.md`, and anything deferred.

   Open the pull request from that file: `gh pr create --base main --head story/<ticket-id> --title "<title>" --body-file <a copy of the file without its first two lines>`. Print the pull request's URL.

   If `gh` fails, print its error, the path of the file, and a link that opens the pull request form already filled in: `https://github.com/<owner>/<repo>/compare/main...story/<ticket-id>?expand=1&title=<title>&body=<body>`, with the title and body URL-encoded (take owner and repo from `git remote get-url origin`). If that link would be longer than 8000 characters, print it without `title` and `body` and say to paste them from the file.

   Then stop. The lap now waits for CI and the human.

## B. Fix round (the user pastes a failing check)

1. Make sure you are on the lap's branch.
2. Read the failure.
   - `gates`: reproduce with `PORT=<port> bash harness/run-gates.sh`, fix, run again until green.
   - `protected-paths` or `scope-guard`: you changed something you may not change. Revert that part. If the ticket cannot be done without it, stop and say so.
3. Commit and `git push`. Tell the user in one line what you changed.
4. At most **3** fix rounds per lap in total. After that, stop and recommend that the product owner split or rewrite the ticket.

## C. After the merge (the user says it merged)

A dispatched lap skips this section: the dispatcher marks the ticket done on `main`, removes the worktree and writes the lap report.

1. Get onto the merged `main`.
   - Main checkout: `git switch main && git pull`.
   - Worktree: `main` is checked out in the main checkout, so `git fetch origin && git switch --detach origin/main`.
2. Ask the product owner skill (`bmad-agent-po`, BOARD) to mark the ticket done, and commit it.
   - Main checkout: `git push`.
   - Worktree: `git push origin HEAD:main`. If it is refused because `main` moved, `git fetch origin && git rebase origin/main` (one local commit, not yet pushed) and push again. Never force-push.
3. Report one line: ticket, number of fix rounds, which checks had failed on the way. In a worktree, also say the worktree can now be removed (`git worktree remove <path>`; in the Claude desktop app, archiving its session does it).

## D. Main moved (the branch is behind `origin/main`)

Run this when step 8 finds `origin/main` ahead, when the user says main moved, or when the pull request shows a conflict or is out of date.

1. `git fetch origin && git merge origin/main`. Merge, never rebase: the branch is pushed and force-push is not allowed.
2. Conflicts: resolve them in application and test code only, keeping both changes' behaviour. If a conflict is in a factory file or cannot be resolved without changing what the other change does, stop and report.
3. Run `PORT=<port> bash harness/run-gates.sh` until green, then `git push`. CI judges the merged result again.
4. A clean merge with no conflict is not a fix round. A merge that needed conflicts resolved, or code changed to get the gates green, counts as one (section B, rule 4). Tell the user in one line what came in from `main` and what you reconciled.
