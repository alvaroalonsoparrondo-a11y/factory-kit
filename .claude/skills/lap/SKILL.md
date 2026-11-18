---
name: lap
description: 'Runs one factory lap: takes exactly one ticket from the BMAD board through build, review and local gates, pushes a branch and opens its pull request for a human to merge. Use when the user says "run a lap", "lap <ticket id>", "next ticket", pastes a failing check from a lap pull request, or says a lap pull request was merged.'
---

# Lap

One ticket, one branch, one pull request. You build; CI judges; a human merges. Follow the steps in order. Never skip one.

Hard rules for the whole lap (from `FACTORY_RULES.md`):

- Never change a factory file during a lap. Never weaken a test. Never look for the holdouts.
- Open the lap's pull request with `gh`. Never label, approve or merge a pull request; a human merges.
- If you cannot finish within the limits below, stop and report. A stopped lap is a correct result.

## A. New lap

1. **Check the start state.** `git status` must be clean and the branch must be `main`, up to date with `origin/main`. If not, stop and say what is in the way.
2. **Pick the ticket.** Use the id the user gave. If they gave none, ask the product owner skill (`bmad-agent-po`, BOARD) for the next ready ticket in build order and confirm it with the user in one line.
3. **Read** `MISSION.md`, `FACTORY_RULES.md`, `harness/README.md` and the ticket, in full.
4. **Branch.** `git switch -c story/<ticket-id>`, then `git push -u origin story/<ticket-id>` at once. The board now shows the lap as started.
5. **Irreversible check.** If the ticket needs anything in `FACTORY_RULES.md` section 1 or a protected path, stop. Do not build a partial version. Make the stop visible on the board: ask the product owner skill (`bmad-agent-po`, BOARD) to mark the ticket blocked with the rule as the reason (`tickets.py mark <ref> draft --blocked "<rule and why>"`), commit, `git push`. Then tell the user which rule applies.
6. **Build with BMAD.** Invoke the `bmad-build` skill with the ticket. Follow its workflow fully, including its review step. It commits locally. It must not push. One push is yours: when the plan is approved, commit the plan file if `bmad-build` has not, and `git push`, so the board shows the ticket as building. Then let `bmad-build` continue.
7. **Local gates.** Run `bash harness/run-gates.sh`.
   - Green: go on.
   - Red: fix the cause in application or test code and run again. At most **3** fix rounds. Still red after 3: stop and report the failing output.
8. **Push.** `git push`. Nothing else.
9. **Hand over.** Write the pull request text to `.lap/<ticket-id>-pr.md`. Git ignores `.lap/`; never commit it.
   - First line: the title, `<ticket-id>: <ticket title>`. Then one blank line.
   - Then the body, filling in every part of `.github/pull_request_template.md`: the ticket, what changed, the local gate result with the candidate id it printed, each assumption made on an open question in `MISSION.md`, and anything deferred.

   Open the pull request from that file: `gh pr create --base main --head story/<ticket-id> --title "<title>" --body-file <a copy of the file without its first two lines>`. Print the pull request's URL.

   If `gh` fails, print its error, the path of the file, and a link that opens the pull request form already filled in: `https://github.com/<owner>/<repo>/compare/main...story/<ticket-id>?expand=1&title=<title>&body=<body>`, with the title and body URL-encoded (take owner and repo from `git remote get-url origin`). If that link would be longer than 8000 characters, print it without `title` and `body` and say to paste them from the file.

   Then stop. The lap now waits for CI and the human.

## B. Fix round (the user pastes a failing check)

1. Make sure you are on the lap's branch.
2. Read the failure.
   - `gates`: reproduce with `bash harness/run-gates.sh`, fix, run again until green.
   - `holdouts`: you get only an ID such as `H-03`. Do not ask for more. Re-read the ticket and `MISSION.md`, find a requirement or invariant the change does not meet, add a test that shows it, then fix it.
   - `protected-paths` or `scope-guard`: you changed something you may not change. Revert that part. If the ticket cannot be done without it, stop and say so.
3. Commit and `git push`. Tell the user in one line what you changed.
4. At most **3** fix rounds per lap in total. After that, stop and recommend that the product owner split or rewrite the ticket.

## C. After the merge (the user says it merged)

1. `git switch main && git pull`.
2. Ask the product owner skill (`bmad-agent-po`, BOARD) to mark the ticket done.
3. Report one line: ticket, number of fix rounds, which checks had failed on the way.
