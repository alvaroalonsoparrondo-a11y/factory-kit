# How to change the factory

The factory is improved while it is used. This page says how a change is requested, where it is made, and how a project takes it.

## The two kinds of repository

- **The kit** (`factory-kit`): the source of truth for the factory. No product code. Its tool is `bin/kit.py`.
- **A project** (for example `factory-pilot`): made from the kit with `kit.py init`. It holds a product plus the factory files.

Every file in a project is one of four kinds. The kit's `bin/kit.py` decides which, by where the file lives in the kit:

| Kind | Where it lives in the kit | What an update does to it |
|---|---|---|
| **The kit's** | `template/`, at the same path the project has it: `AGENTS.md`, `CLAUDE.md`, `FACTORY_RULES.md`, `RUNBOOK.md`, `MODIFYING.md`, `harness/`, `.github/` (except `CODEOWNERS`), the `lap` skill, `_bmad/custom/`, `.gitattributes` | Replaced when the kit changed it |
| **The project's** | `seed/`: `MISSION.md`, `README.md`, `PROJECT_NOTES.md`, `.github/CODEOWNERS`, `.claude/launch.json`. Also `skills-lock.json`, `docs/runtime/` and every file the kit does not have | Never touched. `init` copies the seeds once |
| **The fence** | `template/.claude/settings.json`, `template/.kiro/agents/factory.json` | The kit's deny entries are added or removed. The project's own entries and other settings stay |
| **Merged lines** | `template/.gitignore` | Missing lines are appended. No line is removed |

A project may add its own deny rules to the fence. It may not remove the kit's: `kit.py doctor` fails if a protected path is no longer denied.

`kit.lock.json` in the project records the kit revision it has, a hash of each of the kit's files as installed, and the kit's fence entries. Only `kit.py` writes it, and it is a protected path.

## Rule 1: a change starts as an issue in the kit

Open an issue in `factory-kit`: what was seen, in which project and lap, and why it is the factory's fault rather than the ticket's. The change is then made in the kit (below).

While the kit is young (`bin/kit.json` says `"phase": "young"`), a change may also start in a project, so a lap can be run again with the fix. It must reach the kit soon after (see "While the kit is young"). Once the kit is mature, a change made in a project stops `kit.py sync` and fails `kit.py doctor`.

## Rule 2: factory changes and product changes never share a commit

A factory change touches a protected path, so in a project it needs its own pull request with the label `human-judge-change`. Keep that pull request to factory files only. If a ticket needs both, make two pull requests.

## Rule 3: a human makes factory changes

The agent that runs laps may not edit these files, and the fence stops it. Make the change yourself, or in a separate agent session that you direct and review, on a branch named `factory/<short-name>`. Never during a lap.

## Rule 4: every factory change is written down, in the kit

Add an entry to the kit's `CHANGELOG.md` in the same pull request: what went wrong, in which project and lap (or which issue), and what changed. Projects keep no factory changelog. A change with no observed problem behind it is usually not worth making.

## Making a change in the kit

1. In a clone of `factory-kit`, branch `factory/<short-name>` from `main`.
2. Change the files in `template/` (or `seed/` for what new projects start with). The kit's fence is off, so an agent you direct may edit them.
3. Run the kit's tests: `python -m unittest discover -s bin` and the harness tests under `template/harness/`.
4. Add the `CHANGELOG.md` entry and open the pull request; the agent may open it with `gh`. A human merges it.

## Taking an update from the kit

In the project, with a clone of `factory-kit` next to it and its `main` up to date:

```bash
python ../factory-kit/bin/kit.py status    # what the kit has that this project does not
python ../factory-kit/bin/kit.py sync      # a human runs this: it writes fenced files
```

`sync`:
- refuses a dirty tree;
- creates the branch `factory/sync-<revision>`;
- applies the update and writes `kit.lock.json`;
- runs `doctor`;
- writes a pull request body and prints its path.

Then commit, push and open the pull request with that body; the agent may do this part. A human adds `human-judge-change` and merges when the checks are green.

If a file was changed by both the project and the kit, the change that reached `main` later wins. The other stays in Git history, and the pull request body names it.

## While the kit is young: a change made in a project

`kit.py status` lists the files the project changed that the kit does not have yet. Copy each into `template/` at the same path, on a `factory/<short-name>` branch in the kit, and follow "Making a change in the kit". No file the kit owns holds a project name, so nothing needs editing on the way. The project's next `sync` sees the kit has the same text and only updates the lock.

## Changes that need extra care

| Change | Why | Do this as well |
|---|---|---|
| `harness/run-gates.sh`, or anything that makes a gate easier to pass | It weakens the judge | Run `bash harness/calibrate.sh` before and after. Every defect must still be `CAUGHT`. |
| `.github/workflows/judge-guards.yml` | It uses `pull_request_target`, which has access to secrets | Never add a step that checks out or runs pull request code. |
| The protected-path list | It appears in five places | Change all five together: `FACTORY_RULES.md` section 2, the two fence files (`.claude/settings.json`, `.kiro/agents/factory.json`), `.github/CODEOWNERS`, and the `protected-paths` pattern in `harness/judge/guards.json` (read by both `judge-guards.yml` and the factory judge). In the kit, the first four live in `template/` and `seed/`. `kit.py doctor` checks the two fence files against `guards.json` and warns about `CODEOWNERS`; `FACTORY_RULES.md` is yours to check. Existing projects get the fence change on their next `sync`; their `CODEOWNERS` is theirs, so tell them. |
| `harness/runtime/verify.py` or `verifier.md` | They decide whether the running app does what the ticket says | Run `python -m unittest discover -s harness/runtime`. Keep the scenario read from `main`, the checkout guard, and evidence as one file per assertion inside the attempt's folder. |
| `harness/judge/classify.py` patterns | A pattern that also matches a failure the change can cause lets the change escape the round budget | Add a pattern only for a machine failure seen in a real log, and add that log line to its test; also add a line the change can cause that it must not match. |
| `harness/judge/judge.py` | It runs pull request code where Actions is not allowed | Keep `harness/` taken from `main`, and no token in the gate's environment. Run `python -m unittest discover -s harness/judge`; its Git tests prove both. |
| `harness/judge/guards.json` or `guards.py` | The two guards, for the workflow and for the factory judge alike | Run `python -m unittest discover -s harness/judge`. The workflow must keep calling `guards.py` and hold no pattern of its own. |
| The `lap` skill | Each agent reads its own copy | Change `.claude/skills/lap/SKILL.md`, then copy it to `.kiro/skills/lap/SKILL.md`. The `gates` workflow fails while the two differ. |
| The agent instructions | Claude Code and Kiro read one file | Change `AGENTS.md`. `CLAUDE.md` only imports it (`@AGENTS.md`); keep it that way. |
| The runtime contract in `harness/README.md` | Gates and BMAD's architect rely on it | Update `harness/run-gates.sh` and `_bmad/custom/bmad-architecture.toml` if they mention the item. |
| `harness/rounds.json` or `harness/board/lap_round.py` | The budget is what keeps a lap's cost bounded | Run `python -m unittest discover -s harness/board` and `-s harness/dispatch`. A new kind of check that can send work back adds a source here, not a limit of its own. |
| `_bmad/custom/*.toml` | BMAD merges these with its defaults | Check with `uv run --no-cache _bmad/scripts/resolve_customization.py --skill .claude/skills/<skill> --project-root . --key workflow` (or `--key agent`). |
| How a new project is set up | The steps exist in two forms: for a person and for an agent | Change the kit's `AGENT_SETUP.md` and the one-time setup in `RUNBOOK.md` together, and `kit.py init` if a step is automated. Do not put steps in the kit's README prompt; it only points to `AGENT_SETUP.md`. |
| A BMAD upgrade | Skill names and customisation keys can change | Upgrade in one project first and run a lap. Then change the version named in `RUNBOOK.md`'s install step in the kit. `skills-lock.json` is each project's own. |

## What not to change in a project

- BMAD's own files under `.claude/skills/bmad*` and `_bmad/` (except `_bmad/custom/`). They are overwritten on every BMAD update. Use `_bmad/custom/`.
- The factory files during a lap, to get a red check green. If a check is wrong, stop the lap, fix the check as a factory change, then start the lap again.
