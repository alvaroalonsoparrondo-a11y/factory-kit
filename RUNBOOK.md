# Runbook

How to set up this project and run laps. To change the factory itself, see [MODIFYING.md](MODIFYING.md).

You drive the factory by hand at three points: you start each lap, you merge the pull request the lap opens, and you paste red checks back. The agent uses `gh` only to open a lap's pull request; it never labels, approves or merges one.

## One-time setup

1. **Fill in the placeholders** (only if `init-project.sh` is still in this folder): `bash init-project.sh __OWNER__ __PROJECT__`, then commit and push. On GitHub Enterprise, add the host as a third value: `bash init-project.sh __OWNER__ __PROJECT__ github.example.com`.
2. **Install BMAD v7** in this folder (needs Node and `uv`):

   ```bash
   npx -y skills add bmad-code-org/BMAD-METHOD/skills/core-tools --skill '*' -a claude-code -a kiro-cli -y
   ```

   ```bash
   npx -y skills add bmad-code-org/BMAD-METHOD/skills/method --skill '*' -a claude-code -a kiro-cli -y
   ```

   Then, in an agent session here, say `bmad setup`. Commit what it created (`.claude/skills/`, `.kiro/skills/`, `_bmad/`). Drop `-a kiro-cli` if nobody will use Kiro, or `-a claude-code` if nobody will use Claude Code.
3. **Check the settings.** `.claude/settings.json` (Claude Code) and `.kiro/agents/factory.json` (Kiro) must exist and parse. Their deny rules are the fence: they stop the agent from editing `MISSION.md`, `FACTORY_RULES.md`, `AGENTS.md`, `CLAUDE.md`, `harness/`, `.github/`, either agent's settings, the `lap` skill and `_bmad/custom/`, and from force-pushing.
4. **Create two labels** in `__PROJECT__`: `human-judge-change` and `human-approved-irreversible`.
5. **Protect `main`** in `__PROJECT__` (Settings → Branches): require a pull request, and require these status checks: `gates`, `protected-paths`, `scope-guard`. A check can only be selected after it has run once, so open a first small pull request (for example, the filled-in `MISSION.md`, with the `human-judge-change` label) and then add the checks.
   - Approvals: 1, by someone other than the person who ran the lap. On a one-person trial: 0, because GitHub does not let you approve your own pull request.
   - On a free GitHub plan, branch protection is not enforced on private repositories. The checks still run and show red or green; you have to respect them yourself.
   - Where GitHub Actions is not allowed (see "Without GitHub Actions" below), start the factory judge first; the three checks then report as commit statuses. Without the judge, require the pull request but not the checks: they would never report, so no pull request could merge except by an admin bypassing the rule.
6. **Link the kit**, so factory changes can travel: `git remote add kit https://__HOST__/__OWNER__/factory-kit.git`. If the kit exists only as a local clone, give its folder instead: `git remote add kit <path to factory-kit>`.

## Plan the product (BMAD, interactive, in this folder)

1. `bmad-agent-pm` — write the PRD with John. For a first project pick something small: five to eight stories.
2. **You** fill in `MISSION.md` from the PRD and merge it. The agent is not allowed to.
3. `bmad-architecture` — it already knows the stack and the runtime contract in `harness/README.md`.
4. `bmad-agent-po` — Sofia slices the epic into tickets. The first one is the walking skeleton.
5. Commit the planning documents to `main`.

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

- **claims** each ready ticket once, by creating `story/<ref>` on GitHub (if the branch already exists, someone else has the ticket and it is skipped), and checks it out in its own worktree, `<parent>/__PROJECT__-wt/story-<ref>`, with its own gate port (8091, 8092, …);
- **starts** the lap there, headless (`claude -p "lap <ref>"`), or, with `--no-agents`, tells you to start it;
- **routes** what happens next: a red `gates` gets a fix round with the check's output, a pull request behind `main` gets a "main moved" round, a red guard and a green pull request go to you;
- **closes** a merged lap: marks the ticket done on `main` (as the lap's section C does), pulls `main` in the main checkout if it is clean and on `main`, removes the worktree, and writes a lap report line.

A ticket is ready when every ticket in its `after` is merged and their post-merge actions are done, it has no `story/<ref>` branch, it is not blocked or human-in-the-loop, and its `touches` do not overlap a lap in flight. **A ticket without `touches` runs alone**, so give tickets `touches` (the product owner does this when slicing) before you expect parallel laps. At most two headless laps run at once (`--cap`).

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
- stopped laps, never retried until you `release` them: an error exit, no push, a fix round that pushed nothing, still red after 3 fix rounds, a blocked ticket;
- a red guard (label it or send it back), and green pull requests to review and merge;
- ready human-in-the-loop tickets, and laps you started by hand (reported, never touched);
- post-merge actions (below).

A usage limit or an outage is not a stop: the lap's session is resumed 30 minutes later (up to six times), and it does not count as a fix round.

**Post-merge actions.** A ticket may carry steps a human takes after its merge; until each check holds, it is listed under "Needs you" and the tickets after it wait:

```toml
[[entry.post_merge]]
what = "commit empty harness/skeleton.lock (judge change, label human-judge-change)"
done_when = "file:harness/skeleton.lock"
```

`file:<path>` (the file is on `origin/main`) is the only check so far. The product owner adds `post_merge`, `touches` and the epic's `shared` files when slicing (`_bmad/custom/bmad-agent-po.toml`).

## Follow the tickets

The board is one page with a row per ticket: its stage, its status, what it needs from you, and how often it was reviewed. Open `BOARD.md` on the `board` branch:

`https://__HOST__/__OWNER__/__PROJECT__/blob/board/BOARD.md`

- The `board` workflow rebuilds it on every push to `main` or a `story/` branch, on every pull request change, and when a check finishes. To rebuild by hand, run the `board` workflow from the Actions tab.
- It is built from Git, GitHub and the BMAD files. It stores nothing itself, and the lap agent cannot write to it.
- Reviews are shown as three numbers: BMAD review passes / fix rounds / human reviews. Passes are counted from the plan's Review Triage Log, followed by its findings (found, patched, deferred) when the table can be read.
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

Per lap: fix rounds; which check failed; anything the agent tried to change that it should not. When a lap shows a problem in the factory itself, fix it as [MODIFYING.md](MODIFYING.md) describes and add it to the kit's `CHANGELOG.md`.

## Limits to keep in mind

- The fence here is a guard rail, for both agents. A shell command can still read or write a denied path. The real enforcement is the three required checks.
- The workflows assume Java 21 + Spring Boot + Maven in `backend/`, Angular in `frontend/`, Playwright in `e2e/`.

## Without GitHub Actions

Some organisations' GitHub (often GitHub Enterprise) does not allow Actions. Check with `gh api repos/__OWNER__/__PROJECT__/actions/permissions`: `"enabled": false` means no workflow runs. Do not switch Actions on without your organisation's approval. Then the **factory judge** stands in for the workflows:

```bash
git clone https://__HOST__/__OWNER__/__PROJECT__.git judge-__PROJECT__   # its own clone, not a lap's
cd judge-__PROJECT__
python harness/judge/judge.py --once --dry-run   # what it would post and run
python harness/judge/judge.py                    # keep it running: one pass every two minutes
```

Each pass reads the open pull requests and posts the same three results the workflows post, as commit statuses. The board, the dispatcher and branch protection read commit statuses as they read checks, so nothing else changes.

- **`protected-paths` and `scope-guard`**, for every open pull request on every pass. They are judged by `harness/judge/guards.py`, the same code `judge-guards.yml` runs. A hit still needs your label.
- **`gates`**: `harness/run-gates.sh` on the pull request merged with `main`, with `harness/` taken from `main`, so a pull request cannot change the gate that judges it. Then on `main` itself, after each merge. One gate run per pass, oldest pull request first, with a 30-minute limit; each commit is judged once.
  - A red gate's last log lines go into one comment on the pull request, edited in place. The dispatcher's fix round reads that comment.
  - A pull request that conflicts with `main` gets no `gates` status; it needs a "main moved" round.
- **What the machine needs:** Java 21, Node 22, Git, Python 3.11+, and a free port 8190 (`--port`). `--no-gates` runs the two guards only, on a machine without Java or Node.
- **The token:** `FACTORY_JUDGE_TOKEN`, else your `gh` login. It needs Pull requests read and write and Commit statuses write, and must never reach a lap. The gate runs pull request code with no token in its environment; still, run the judge on a machine where nothing else secret is reachable.
- **Its records:** verdicts and gate logs are kept in `.factory/judge/` in its clone (ignored by Git).
- **`calibrate`:** run `bash harness/calibrate.sh` in the judge's clone.
- **The board** on the `board` branch is not rebuilt; use the live board (`python harness/board/serve.py`).
- **Branch protection:** once the judge has posted each status once, require all three: `gates`, `protected-paths` and `scope-guard`. A required status that never reports blocks every merge, so do this only while the judge runs.

When the judge is not running, nothing is judged. Then run `bash harness/run-gates.sh` on the lap's branch yourself, and read its changed files against the patterns in `harness/judge/guards.json`, before you merge.

Two limits remain. The judge runs only while its machine is on. And anyone with write access can post a status, including a lap's `gh`. The judge overwrites a status that disagrees with its own verdict on its next pass, at most two minutes later, but a merge could land in between. Trusting only the judge's own statuses, and running the judge on a shared machine, are the next steps.
