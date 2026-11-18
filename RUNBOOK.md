# Runbook

How to set up this project and run laps. To change the factory itself, see [MODIFYING.md](MODIFYING.md).

You drive the factory by hand at three points: you start each lap, you merge the pull request the lap opens, and you paste red checks back. The agent uses `gh` only to open a lap's pull request; it never labels, approves or merges one.

## One-time setup

1. **Fill in the placeholders** (only if `init-project.sh` is still in this folder): `bash init-project.sh __OWNER__ __PROJECT__`, then commit and push.
2. **Install BMAD v7** in this folder (needs Node and `uv`):

   ```bash
   npx -y skills add bmad-code-org/BMAD-METHOD/skills/core-tools --skill '*' -a claude-code -y
   ```

   ```bash
   npx -y skills add bmad-code-org/BMAD-METHOD/skills/method --skill '*' -a claude-code -y
   ```

   Then, in a Claude Code session here, say `bmad setup`. Commit what it created (`.claude/skills/`, `_bmad/`).
3. **Check the settings.** `.claude/settings.json` must exist and parse. Its deny list is empty: the fence is off, and the agent is bound by `FACTORY_RULES.md` and `CLAUDE.md` instead (see `CHANGELOG.md`, 2026-11-18).
4. **Create two fine-grained tokens** (GitHub → Settings → Developer settings). Create them yourself; never give them to the agent.

   | Token | Repository access | Permissions | Store as |
   |---|---|---|---|
   | Dispatch | `__PROJECT__-holdouts` only | Contents: read and write | Secret `HOLDOUTS_DISPATCH_TOKEN` in `__PROJECT__` |
   | Status | `__PROJECT__` only | Contents: read; Commit statuses: read and write | Secret `APP_REPO_TOKEN` in `__PROJECT__-holdouts` |

5. **Set two repository variables** (Settings → Secrets and variables → Actions → Variables):
   - in `__PROJECT__`: `HOLDOUTS_REPO` = `__OWNER__/__PROJECT__-holdouts`
   - in `__PROJECT__-holdouts`: `APP_REPO` = `__OWNER__/__PROJECT__`
6. **Create two labels** in `__PROJECT__`: `human-judge-change` and `human-approved-irreversible`.
7. **Protect `main`** in `__PROJECT__` (Settings → Branches): require a pull request, and require these status checks: `gates`, `protected-paths`, `scope-guard`, `holdouts`. A check can only be selected after it has run once, so open a first small pull request (for example, the filled-in `MISSION.md`, with the `human-judge-change` label) and then add the checks.
   - Approvals: 1, by someone other than the person who ran the lap. On a one-person trial: 0, because GitHub does not let you approve your own pull request.
   - On a free GitHub plan, branch protection is not enforced on private repositories. The checks still run and show red or green; you have to respect them yourself.
8. **Link the kit**, so factory changes can travel: `git remote add kit https://github.com/__OWNER__/factory-kit.git`

## Plan the product (BMAD, interactive, in this folder)

1. `bmad-agent-pm` — write the PRD with John. For a first project pick something small: five to eight stories.
2. **You** fill in `MISSION.md` from the PRD and merge it. The agent is not allowed to.
3. `bmad-architecture` — it already knows the stack and the runtime contract in `harness/README.md`.
4. `bmad-agent-po` — Sofia slices the epic into tickets. The first one is the walking skeleton.
5. Commit the planning documents to `main`.

## Write the hidden scenarios (separate session, in `../__PROJECT__-holdouts`)

Open a **different** agent session in the `-holdouts` folder. Give it the PRD and `MISSION.md`. Ask for three or four scenarios beyond `H-00`. Commit and push there. Never do this in the session that runs laps.

## Run laps

In an agent session opened in this folder:

1. Say `run a lap` (or `lap <ticket id>`).
2. When it stops, it has opened the pull request and printed its URL. If `gh` failed, it printed a link that opens the form filled in (the text is also in `.lap/<ticket id>-pr.md`): open it and create the pull request.
3. Watch the four checks.
   - All green: merge, then tell the session `merged`.
   - Red: copy the failing check's name and output, paste it into the session. For `holdouts`, paste only the status line (`failed: H-03`).
4. After the walking skeleton merges: commit an empty `harness/skeleton.lock` (a factory change, by you).

## Follow the tickets

The board is one page with a row per ticket: its stage, its status, what it needs from you, and how often it was reviewed. Open `BOARD.md` on the `board` branch:

`https://github.com/__OWNER__/__PROJECT__/blob/board/BOARD.md`

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

- It uses your own `gh` login (or `GITHUB_TOKEN`) for pull requests and checks; without either it shows Git only.
- The branch checked out in this folder is read from the working tree, so a running lap shows its plan before it is pushed.
- It binds `127.0.0.1` only and never reads the holdouts repository.
- **A lap that waits for you** goes to "Needs you" with the reason and how long it has waited, for example "Approve the plan (approval, waiting 12 min)". The lap writes this itself with `python harness/board/lap_signal.py` into `.lap/<ticket-id>.jsonl`, so it is the agent's own word, never evidence. A wait is dropped once the branch has a newer commit, or the ticket is done.
- **Quiet** means the lap on the branch checked out here is not waiting, yet nothing in the folder (build output included) has changed for 10 minutes: look at the session, it may have hit a usage limit, crashed, or be stuck on a permission prompt. Change the threshold with `--quiet-minutes`. A lap in another clone needs its own `serve.py --root <that folder>`.
- The card's `n stops · m min` is the time the lap said it waited for you. Hover the `B…` chip for the triage log's findings; the drawer lists every stop.
- The browser tab's title starts with `(!) <n>` while something waits for you.

## Calibrate the judge

After two or three tickets, add deliberate defects (see `harness/mutations/README.md`) and run the `calibrate` workflow from the Actions tab, or `bash harness/calibrate.sh` locally.

## What to record

Per lap: fix rounds; which check failed; whether a hidden scenario caught something the build session had called done; anything the agent tried to change that it should not. When a lap shows a problem in the factory itself, fix it as [MODIFYING.md](MODIFYING.md) describes and add it to the kit's `CHANGELOG.md`.

## Limits to keep in mind

- There is no fence: the deny list is empty, so the rules bind the agent only by instruction. The real enforcement is the four required checks.
- The workflows assume Java 21 + Spring Boot + Maven in `backend/`, Angular in `frontend/`, Playwright in `e2e/`.
