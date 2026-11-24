# Runbook

How to set up this project and run laps. To change the factory itself, see [MODIFYING.md](MODIFYING.md).

Notes that belong to this project only (who runs it, its setup status, what it does not prove) are in [PROJECT_NOTES.md](PROJECT_NOTES.md). This file comes from the kit (`factory-kit`) and is replaced when the project takes an update.

You drive the factory by hand at three points: you start each lap, you merge the pull request the lap opens, and you paste red checks back. The agent uses `gh` only to open a lap's pull request; it never labels, approves or merges one.

## One-time setup

1. **Install the factory** (only for a new project; skip it if `kit.lock.json` exists). Create an empty repository on GitHub (or GitHub Enterprise) and clone it. Clone `factory-kit` into the same parent folder. Then, from this project's root, run `python ../factory-kit/bin/kit.py init --owner <user or team>`, and commit and push what it wrote.
2. **Install BMAD v7** in this folder (needs Node and `uv`):

   ```bash
   npx -y skills add bmad-code-org/BMAD-METHOD/skills/core-tools --skill '*' -a claude-code -a kiro-cli -y --copy
   ```

   ```bash
   npx -y skills add bmad-code-org/BMAD-METHOD/skills/method --skill '*' -a claude-code -a kiro-cli -y --copy
   ```

   `--copy` puts real files in `.claude/skills/` and `.kiro/skills/`. Without it, the skills CLI keeps one copy in `.agents/skills/` and links the agents' folders to it; `.agents/` is not committed, so a clone would get broken links. `kit.py doctor` reports linked skill folders.

   Then, in an agent session here, say `bmad setup`. Commit what it created (`.claude/skills/`, `.kiro/skills/`, `_bmad/`). Drop `-a kiro-cli` if nobody will use Kiro, or `-a claude-code` if nobody will use Claude Code. The kit was last tested with the BMAD version `bmad setup` reports as `6.13.0-next`; BMAD itself records what it installed in `skills-lock.json`, which is this project's file, not the kit's.
3. **Check the settings.** `.claude/settings.json` (Claude Code) and `.kiro/agents/factory.json` (Kiro) must exist and parse. Their deny rules are the fence: they stop the agent from editing `MISSION.md`, `FACTORY_RULES.md`, `AGENTS.md`, `CLAUDE.md`, `harness/`, `.github/`, either agent's settings, the `lap` skill and `_bmad/custom/`, and from force-pushing.
4. **Create three labels** in this repository: `human-judge-change`, `human-approved-irreversible` and `human-granted-round` (the factory judge's way to give a lap one more round; see "The round budget").
5. **Protect `main`** in this repository (Settings → Branches): require a pull request, and require these status checks: `gates`, `protected-paths`, `scope-guard`. A check can only be selected after it has run once, so open a first small pull request (for example, the filled-in `MISSION.md`, with the `human-judge-change` label) and then add the checks.
   - Approvals: 1, by someone other than the person who ran the lap. On a one-person trial: 0, because GitHub does not let you approve your own pull request.
   - On a free GitHub plan, branch protection is not enforced on private repositories. The checks still run and show red or green; you have to respect them yourself.
   - Where GitHub Actions is not allowed (see "Without GitHub Actions" below), start the factory judge first; the three checks then report as commit statuses. Without the judge, require the pull request but not the checks: they would never report, so no pull request could merge except by an admin bypassing the rule.
6. **Check what is still open.** `python ../factory-kit/bin/kit.py doctor` checks the fence, then lists each setup step still open, as `open:` lines: GitHub Actions switched off (then see "Without GitHub Actions" below: nothing judges a pull request until you run the judge), a missing label, `main` not protected or not requiring the three checks (or protection not available on your plan), BMAD not installed, no active initiative. It asks GitHub through your `gh` login; `--offline` skips that. `kit.py init` runs it at the end, too. An open step never fails `doctor`, but read each one before you plan.
7. **Keep the factory up to date.** `python ../factory-kit/bin/kit.py status` shows which kit changes this project does not have yet. To take them, see "Taking an update from the kit" in [MODIFYING.md](MODIFYING.md).

## Plan the product (BMAD, interactive, in this folder)

`main` takes changes only through pull requests, and a lap reads its ticket and its runtime scenario from `main`. So each planning step below ends in its own pull request, from a branch `planning/<step>` (for example `planning/prd`, `planning/architecture`, `planning/tickets`):

- The agent commits on that branch, cut from `origin/main`, never on `main`. When you say the step is done, it pushes the branch and opens the pull request with `gh` (title `planning: <step>`; the template's Ticket section says `none: planning`; the evidence lines that only apply to a lap can say `n/a`).
- It is judged like any other pull request. `gates` passes with "no backend yet" until the walking skeleton merges. A planning pull request that touches a protected path (`MISSION.md`) needs `human-judge-change`.
- Without GitHub Actions, nothing judges it until you run the judge: `python harness/judge/judge.py --once --pr <number>`, and after you merge it, `python harness/judge/judge.py --once` to judge the new `main`.

0. **You** set the active BMAD initiative; the agent cannot, because `_bmad/custom/` is fenced (a personal `*.user.toml` there can override the team's rules, such as the review lenses). Create `_bmad/custom/config.user.toml` with:

   ```toml
   [core]
   active_initiative = "initiative-<name>"
   ```

   `<name>` is the product's short name in kebab-case. Git ignores the file, so do this in every clone you plan in. The initiative's folder and its file are made by the planning skills; if one asks you to set or create an initiative, the line above is the answer. `kit.py doctor` reports a missing initiative.
1. `bmad-agent-pm` — write the PRD with John. For a first project pick something small: five to eight stories.
2. **You** fill in `MISSION.md` from the PRD and merge it. The agent is not allowed to.
3. `bmad-architecture` — it already knows the stack and the runtime contract in `harness/README.md`. The kit's rules make it pin versions from Maven Central and `npm view`, check every property or API an AD names against the pinned version, and add a reviewer for both.
4. `bmad-agent-po` — Sofia slices the epic into tickets and writes their runtime scenarios (`docs/runtime/`). The first ticket is the walking skeleton. It is the one ticket exempt from the fifteen-minute review size, and its generated starter files go in their own first commit (`starter:`), which the lap's review leaves out.
5. Merge the last planning pull request. Then run a lap.

The reasons behind decisions live in the documents on `main`: BMAD's decision logs (`.memlog.md`) are working files that Git ignores, so an amended architecture decision carries its reason in the spine itself.

## Triage: plan the next ticket while the factory builds this one

Before a ticket's lap, the `triage` skill reads the ticket, `MISSION.md`, the code on `main` and the board, and picks one route. It only reads; nothing it says changes a file until it is recorded.

| Route | Means | What happens |
|---|---|---|
| `ready-to-implement` | Clear, bounded, nothing to decide | The lap approves its own plan when the plan has no open questions (a human still does for `risk = "high"` or `hitl = true`) |
| `ready-to-spec` | The goal is right, a decision is open | Shows under **Needs you** with the questions. Settle them with Sofia (`refine <ref>`) |
| `needs-info` | Cannot be built or specified yet | Shows under **Needs you** with the questions. Answer them in the ticket |
| `wait` | Not now | Shows under **Needs you**. Change the ticket, or drop it |

A decision is `docs/triage/<ref>.json` on `main`, written by `python harness/board/triage.py <ref> record <answer file> --push`, which commits it straight onto `main` from a throwaway worktree. The dispatcher records its own triages the same way, and when you triage by hand the agent runs it once you say yes. Nobody commits a decision by hand. Without `--push` it only writes the file in your checkout. It goes **stale** when the ticket, its leaf or epic file, or its prerequisites change, or when `main` changes a path in its `touches`: then the ticket is triaged again. So editing the ticket after `ready-to-spec` or `needs-info` is how you send it back. `python harness/board/triage.py <ref> check` says where a ticket stands.

By hand: in a session on an up-to-date `main` (not a lap worktree), say `triage 1.3`; it offers to record the decision and, on your yes, commits it to `main` for you (`record --push`). The dispatcher does it for you (below): while ticket N builds, it triages N+1, so the questions for N+1 reach you before N merges, and it triages N+1 again when N merges and changes its files.

## Run laps

In an agent session opened in this folder. With Kiro, start it as the factory agent, so the fence applies:

```powershell
kiro-cli chat --agent factory
```

To make it the default here, set `chat.defaultAgent` to `factory` in Kiro's settings. Kiro loads workspace agents only once you trust the folder.


1. Say `run a lap` (or `lap <ticket id>`).
2. When it stops, it has opened the pull request and printed its URL. If `gh` failed, it printed a link that opens the form filled in (the text is also in `.lap/<ticket id>-pr.md`): open it and create the pull request.
3. Watch the three checks.
   - All green: merge, then tell the session `merged`.
   - Red: copy the failing check's name and output, paste it into the session.
4. After the walking skeleton merges: commit an empty `harness/skeleton.lock` (a factory change, by you).

### A big lap in a worktree

To keep working in this folder while a big lap runs, start the lap in a Claude Code session that has its own worktree (in the desktop app, a new session with a worktree) and say `lap <ticket id>` there. The lap branches `story/<ticket id>` from `origin/main`, runs its gates on port 8081 (8080 stays free for you), and opens its pull request as usual. Then:

- If you push to `main` while it runs, it merges `origin/main` into its branch before it pushes. Tell it `main moved` if its pull request falls behind later.
- After you merge, tell that session `merged`. It marks the ticket done straight onto `main`. Archive the session to remove the worktree.
- The first gate run in a new worktree is slow: it has its own `node_modules` and `backend/target`.

### The dispatcher: laps claimed, routed and closed for you

`harness/dispatch/dispatch.py` is the factory's queue and orchestrator. It is a local script: it cannot receive webhooks, so it polls. Each pass reads the tickets the way the live board does (Git, GitHub, every worktree, lap signals, quiet time) and then:

- **triages** the next ticket in line (every prerequisite done or in flight) when it has no decision or a stale one: a read-only agent (`Read Glob Grep Skill`, no shell, no edits) in a detached worktree of `origin/main`, `<project>-wt/triage-<ref>`, one at a time; the dispatcher checks its answer with `triage.py` and commits `docs/triage/<ref>.json` straight to `main`. With `--no-agents` it asks you to triage instead. A ticket triaged anything but `ready-to-implement` goes to you;
- **claims** each ready ticket once, by creating `story/<ref>` on GitHub (if the branch already exists, someone else has the ticket and it is skipped), and checks it out in its own worktree, `<project>-wt/story-<ref>`, next to this clone, with its own gate port (8091, 8092, …);
- **starts** the lap there, headless (`claude -p "lap <ref>"`), or, with `--no-agents`, tells you to start it;
- **routes** what happens next: a red `gates` gets a fix round with the check's output, a pull request behind `main` gets a "main moved" round, a red guard and a green pull request go to you;
- **closes** a merged lap: marks the ticket done on `main` (as the lap's section C does), pulls `main` in the main checkout if it is clean and on `main`, removes the worktree, and writes a lap report line.

A ticket is ready when its triage is a fresh `ready-to-implement`, every ticket in its `after` is merged and their post-merge actions are done, it has no `story/<ref>` branch, it is not blocked or human-in-the-loop, and its `touches` do not overlap a lap in flight. **A ticket without `touches` runs alone**, so give tickets `touches` (the product owner does this when slicing) before you expect parallel laps. At most two headless laps run at once (`--cap`).

**Two ways to run it:**

- `--no-agents`: the dispatcher claims, sets up the worktree, routes and closes; you run each lap in an agent session in that worktree (Claude Code, or `kiro-cli chat --agent factory`) and paste what it tells you (`lap 1.4`, `lap 1.4 fix round`, `lap 1.4 main moved`). This is the shape that carries to work, where Kiro runs interactively only.
- Headless (Claude Code only, so far): the dispatcher also runs the laps. It refuses while the fence is off (`.claude/settings.json` denies nothing, as now), because a headless lap would then have no guard at all. Turn the fence on, or pass `--allow-no-fence` knowingly. With a fence, `python harness/dispatch/dispatch.py verify-fence` checks that a headless lap obeys it: it runs the exact command the dispatcher uses (`--permission-mode dontAsk` with an allow list, never `bypassPermissions`) on a scratch repository and expects a refused edit to `harness/`, a refused write to `.claude/settings.json`, a refused force push, and an allowed ordinary edit.

**One-time:**

1. GitHub access: `gh auth login` is enough (the dispatcher uses `gh auth token`, or `FACTORY_DISPATCH_TOKEN` / `GITHUB_TOKEN` if set: a fine-grained token for this repository with Contents read and write, Pull requests, Commit statuses, Checks and Actions read). None of these reaches a lap's environment.
2. Settings → Branches → the rule for `main` → tick **Require branches to be up to date before merging**. Without it, two parallel laps can each be green against an older `main` and break it together; with it, a pull request that falls behind gets a "main moved" round.

**Start and stop** (from any checkout; state lives in the main checkout):

```powershell
python harness/dispatch/dispatch.py tick --dry-run --no-agents
```

```powershell
python harness/dispatch/dispatch.py tick --loop 5 --no-agents
```

- `--dry-run` reads everything and prints what a pass would do; it claims, starts and writes nothing.
- `--loop 5` makes a pass every 5 minutes; Ctrl+C stops it. Headless laps already started keep running; the next pass picks them up. Only one pass runs at a time (a lock), so a manual `tick` beside a loop is safe.
- `pause` / `unpause`: no new laps, while laps in flight are still routed and closed.
- `release <ref>`: route a lap again after you dealt with what stopped it. `forget <ref>`: drop it from the dispatcher's memory (branch and worktree stay).

**What it keeps** (under `.factory/` in the main checkout, ignored by Git through its own `.gitignore`): `dispatch-state.json` (laps in flight: port, worktree, stage, session id, fix rounds, failed checks), `logs/<ref>-<nn>-<stage>.log` (one per headless stage), `lap-reports.log` (one line per closed lap: pull request, fix rounds, which checks failed, main-moved rounds, usage-limit pauses; the numbers "What to record" asks for).

**Needs you** ends every pass:

- a lap that stopped for you (its `lap_signal.py` wait), with the command to open its session: `claude --resume <session id>` in its worktree;
- a lap that is quiet for an hour while its process runs (it may have hung; end the process to stop it);
- stopped laps, never retried until you `release` them: an error exit, no push, a fix round that pushed nothing, a spent round budget (see "The round budget" below), behind `main` after 3 main-moved rounds, a blocked ticket;
- a red guard (label it or send it back), and green pull requests to review and merge;
- ready human-in-the-loop tickets, and laps you started by hand (reported, never touched);
- post-merge actions (below).

A usage limit or an outage is not a stop: the lap's session is resumed 30 minutes later (up to six times), and it takes no round.

**Post-merge actions.** A ticket may carry steps a human takes after its merge; until each check holds, it is listed under "Needs you" and the tickets after it wait:

```toml
[[entry.post_merge]]
what = "commit empty harness/skeleton.lock (judge change, label human-judge-change)"
done_when = "file:harness/skeleton.lock"
```

`file:<path>` (the file is on `origin/main`) is the only check so far. The product owner adds `post_merge`, `touches` and the epic's `shared` files when slicing (`_bmad/custom/bmad-agent-po.toml`).

## Follow the tickets

The board is one page with a row per ticket: its stage, its status, what it needs from you, and how often it was reviewed. Open `BOARD.md` on the `board` branch:

`gh browse BOARD.md --branch board`

- The `board` workflow rebuilds it on every push to `main` or a `story/` branch, on every pull request change, and when a check finishes. To rebuild by hand, run the `board` workflow from the Actions tab.
- It is built from Git, GitHub and the BMAD files. It stores nothing itself, and the lap agent cannot write to it.
- Reviews are shown as three numbers: BMAD review passes / rounds used / human reviews. The live board counts rounds from the lap's own record; the `board` workflow, which cannot see it, counts the commits CI judged after the first. Passes are counted from the plan's Review Triage Log, followed by its findings (found, patched, deferred) when the table can be read.
- A merged pull request counts as done.
- Work that is not pushed is not on the board. The lap pushes its branch when it starts, so this is only the first minute of a lap.
- Anything the board cannot read is listed under "Problems" at the bottom.

### The live board on your machine

```bash
python harness/board/serve.py
```

Then open `http://127.0.0.1:8765`. It shows the same tickets as columns of cards (Backlog, Build, Review, CI, Needs you, Done), refreshes every few seconds, and opens a ticket's entry, plan, epic and pull request text when you click its card.

- It uses your own `gh` login (or `GITHUB_TOKEN`) for pull requests and checks; without either it shows Git only. On GitHub Enterprise it takes the host from `origin` and asks `gh` for that host's login; `GITHUB_SERVER_URL` and `GITHUB_API_URL` override it.
- The branch checked out in this folder is read from the working tree, so a running lap shows its plan before it is pushed.
- It binds `127.0.0.1` only.
- **A lap that waits for you** goes to "Needs you" with the reason and how long it has waited, for example "Approve the plan (approval, waiting 12 min)". The lap writes this itself with `python harness/board/lap_signal.py` into `.lap/<ticket-id>.jsonl`, so it is the agent's own word, never evidence. A wait is dropped once the branch has a newer commit, or the ticket is done.
- **Quiet** means a lap is not waiting, yet nothing in the working tree it runs in (this folder or its worktree, build output included) has changed for 10 minutes: look at the session, it may have hit a usage limit, crashed, or be stuck on a permission prompt. Change the threshold with `--quiet-minutes`. A lap in a separate clone, not a worktree, needs its own `serve.py --root <that folder>`.
- The card's `n stops · m min` is the time the lap said it waited for you. Hover the `B…` chip for the triage log's findings; the drawer lists every stop.
- The browser tab's title starts with `(!) <n>` while something waits for you.

## Calibrate the judge

After two or three tickets, add deliberate defects (see `harness/mutations/README.md`) and run the `calibrate` workflow from the Actions tab, or `bash harness/calibrate.sh` locally.

## What to record

Per lap: rounds used, by source; which check failed; anything the agent tried to change that it should not. When a lap shows a problem in the factory itself, fix it as [MODIFYING.md](MODIFYING.md) describes and add it to the kit's `CHANGELOG.md`.

## Limits to keep in mind

- The fence here is a guard rail, for both agents. A shell command can still read or write a denied path. The real enforcement is the three required checks.
- The workflows assume Java 21 + Spring Boot + Maven in `backend/`, Angular in `frontend/`, Playwright in `e2e/`.
- The `gates` workflow uses Node 22, which comes with npm 10. A recent `ng new` writes `"packageManager": "npm@11…"` into `frontend/package.json`. That is harmless while Corepack is off; if you turn Corepack on, make the two agree.

## The round budget

Every lap has one budget of **3 rounds** (`harness/rounds.json`), shared by every check. A round is a fix that is checked again: a review loopback in `bmad-build`, a red local gate fixed and run again, a red check on the pull request, a failed runtime check, a merge of `main` that needed conflicts resolved. The first run of a check, a clean merge of `main`, a failure of the machine (a usage limit, a missing tool, a lost network), and a red that `main` has alone too take no round.

- **Who decides why gates are red.** `harness/judge/classify.py`, never the agent. It reads the gates log and prints `introduced` (the change caused it: a round), `environment` (a known machine failure is in the log: no round), `inherited` (with `--check-main`: the gates are red on `origin/main` alone, too: no round, `main` needs a fix) or `timeout`. A machine failure needs a log line that matches one of its patterns; anything unproven is `introduced`, so the budget cannot be dodged by calling a failure the machine's.

- **How it is kept.** Before each such fix the lap runs `python harness/board/lap_round.py <ref> take <source> "<finding>"`, which records the round in `.lap/<ref>.jsonl` next to the lap's signals. The dispatcher also counts the fix rounds it starts and uses whichever count is higher, so deleting the record buys nothing. `lap_round.py <ref> status` shows the count; the live board shows it on the ticket.
- **How a lap stops.** When the budget is spent, `take` refuses and itself marks the lap as waiting (`limit`), with every finding so far. It also refuses when the same check reports the same finding as the round before: the fix did not reach the cause, and another round would spend the budget one symptom at a time (that stop is a `decision`). Either stop holds: every later `take`, from any check, refuses the same way until you `grant` a round, so the lap cannot move on to another check without your decision.
- **What you do then.** Usually: ask the product owner skill to split or rewrite the ticket. If one more round is worth it: `python harness/board/lap_round.py <ref> grant 1 "<why>"` in the lap's checkout, then tell the lap to go on (for a dispatched lap, `release` it). A `release` alone gives no rounds and lifts no stop: the lap's next `take` refuses again. The fence denies `grant` to the agent.
- **Without GitHub Actions, the judge brakes too.** The factory judge counts the red `gates` runs of each pull request (a timeout does not count: it may be the machine). Once they reach the budget, it judges no new commit and posts `gates` red with "Round budget spent". To give one more round, add the label `human-granted-round` to the pull request; each time it is added counts once, so remove it and add it again for another. This brake holds even when a lap's own record is lost.
- **Changing the budget.** Edit `budget` in `harness/rounds.json`: one number for the whole factory.

## Runtime verification

The gates prove that the tests the builder wrote pass. Runtime verification asks a different agent whether the running app does what the ticket says. Adapted from Archon's `archon-verify-runtime`.

- **The scenario** is `docs/runtime/<ref>.json`, one assertion per acceptance criterion. The product owner writes it when the ticket is planned (`bmad-agent-po` does this), and it is committed to `main` before the lap. The lap reads it from `main` and is refused if its own copy differs, so the builder cannot loosen the test it is judged by.
- **The lap runs it after green gates** (lap step 7). `harness/runtime/verify.py <ref> start` starts the jar fresh with empty data, checks its build identity, makes a new evidence folder and writes the verifier's prompt. A context-free subagent then follows that prompt: it uses the running app, saves raw tool output as evidence and writes a report. `verify.py <ref> check` stops the app and judges the report.
- **What it decides.** `verified`; `failed` (a well-formed report shows the app contradicting an assertion: a `runtime` round); `inconclusive` (something could not be judged, the app's own build identity disagreed, or the verifier wrote in the checkout: no round, the lap stops for you); `malformed` (the report broke its rules, including a build identity the verifier copied wrong while the app's was right: one fresh attempt, then `inconclusive`). The script checks coverage, fields, evidence files and identity; it does not second-guess the observations.
- **What you see.** The pull request carries `verify.py <ref> summary`: the verdict, the candidate and one line per assertion. The evidence stays in the lap's checkout, in `.lap/runtime/<ref>/` (ignored by Git), for when you want to look.
- **Not yet:** it runs only in the lap, not in CI or in the factory judge, and it is not a required check. It costs one agent session per lap, plus at most one retry.

## Without GitHub Actions

Some organisations' GitHub (often GitHub Enterprise) does not allow Actions. Check with `gh api repos/{owner}/{repo}/actions/permissions`: `"enabled": false` means no workflow runs. Do not switch Actions on without your organisation's approval. Then the **factory judge** stands in for the workflows:

**When you run laps yourself** ("run a lap"), you type nothing extra. After the lap opens its pull request, it runs the judge on it (lap step A10):

```bash
python harness/judge/judge.py --once --pr 12 --port 8180
```

The judge checks both guards, then runs the gates on the pull request merged with `main`. It posts the three results on the pull request and prints them in one line. A red `gates` is a fix round the lap does at once, then it runs the judge again, within the lap's round budget ("The round budget" above). So the lap ends in one of two ways: a pull request with three green checks, ready for your review and merge, or a stop that says what it needs from you (a label, a decision, or a judge that could not run). You can run the same command yourself at any time to judge a pull request again. After a merge, `python harness/judge/judge.py --once` judges the new `main`; the lap does this itself when you tell it `merged` (section C). Planning pull requests are not laps: run the judge on them yourself (see "Plan the product").

The lap's agent cannot change what the judge checks: `harness/` is fenced, and the judge takes it from `main`. Posting a status by hand (`gh api …/statuses/…`) is fenced too. The fence is a guard rail, not a lock, so branch protection and your review stay the last word.

**When the dispatcher runs laps,** keep the judge running instead, in its own clone, so every pull request is judged without you:

```bash
python harness/judge/judge.py --once --dry-run   # what it would post and run
python harness/judge/judge.py                    # one pass every two minutes
```

Either way the judge posts the same three results the workflows post, as commit statuses. The board, the dispatcher and branch protection read commit statuses as they read checks, so nothing else changes.

- **`protected-paths` and `scope-guard`**, for every open pull request on every pass. They are judged by `harness/judge/guards.py`, the same code `judge-guards.yml` runs. A hit still needs your label.
- **`gates`**: `harness/run-gates.sh` on the pull request merged with `main`, with `harness/` taken from `main`, so a pull request cannot change the gate that judges it. Then on `main` itself, after each merge. One gate run per pass, oldest pull request first, with a 30-minute limit; each commit is judged once.
  - A red gate's last log lines go into one comment on the pull request, edited in place, with its cause from `classify.py`. The dispatcher's fix round reads that comment.
  - **Why it is red decides what happens.** `introduced` is an ordinary red and counts against the round budget. `inherited` (the judge judges `main` alone, once, to see) is posted red as "Not this change: … red on main alone, too". A machine failure is run again on the next pass; the same commit failing on the machine twice is posted `error`, "Not this change: the machine failed twice", and not run again until you fix the machine and run `judge.py --retry-errors`. Neither takes a round, and the dispatcher sends both to you instead of starting a fix round.
  - A pull request that conflicts with `main` gets no `gates` status; it needs a "main moved" round.
- **What the machine needs:** Java 21, Node 22, Git, Python 3.11+, and a free port 8190 (`--port`). `--no-gates` runs the two guards only, on a machine without Java or Node.
- **The token:** `FACTORY_JUDGE_TOKEN`, else your `gh` login. It needs Pull requests read and write and Commit statuses write, and must never reach a lap. The gate runs pull request code with no token in its environment; still, run the judge on a machine where nothing else secret is reachable.
- **Its records:** verdicts and gate logs are kept in `.factory/judge/` in its clone (ignored by Git).
- **`calibrate`:** run `bash harness/calibrate.sh` in the judge's clone.
- **The board** on the `board` branch is not rebuilt; use the live board (`python harness/board/serve.py`).
- **Branch protection:** once the judge has posted each status once, require all three: `gates`, `protected-paths` and `scope-guard`. Then a pull request cannot merge until the judge has passed it, whether you run the judge on demand or keep it running.

When the judge is not running, nothing is judged. Then run `bash harness/run-gates.sh` on the lap's branch yourself, and read its changed files against the patterns in `harness/judge/guards.json`, before you merge.

Two limits remain. Nothing is judged until you run the judge, or while its machine is off. And anyone with write access can post a status, including a lap's `gh`. The judge overwrites a status that disagrees with its own verdict on its next pass, at most two minutes later, but a merge could land in between. Trusting only the judge's own statuses, and running the judge on a shared machine, are the next steps.
