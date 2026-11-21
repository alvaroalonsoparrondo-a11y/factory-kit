# How to change the factory

The factory is improved while it is used. This page says where a change is made, how it reaches the kit, and how it reaches other projects.

## The two kinds of repository

- **The kit** (`factory-kit`): the source of truth for the factory. No product code.
- **A project** (for example `factory-pilot`): made from the kit. It holds a product plus a copy of the factory files.

The factory files have the same paths in both. That is what makes a change easy to carry across.

**Factory files** — a change to any of these is a factory change:

```
FACTORY_RULES.md   AGENTS.md   CLAUDE.md   RUNBOOK.md   MODIFYING.md   AGENT_SETUP.md
harness/           .github/    _bmad/custom/   .gitattributes
.claude/settings.json          .claude/skills/lap/
.kiro/agents/                  .kiro/skills/lap/
```

**The fence is off in the kit.** The kit is changed by humans and agents they direct, so its own `.claude/settings.json` and `.kiro/agents/factory.json` deny no paths, and the `protected-paths` check skips the kit (it is a template repository). The fenced versions live in `fence/claude-settings.json` and `fence/kiro-factory.json`; `init-project.sh` copies them into place and deletes `fence/`. So a fence change is made in `fence/` in the kit and in `.claude/settings.json` / `.kiro/agents/factory.json` in a project: when you carry one across, move it to the other path.

`MISSION.md` is different: the kit holds only the empty template. A project's filled-in `MISSION.md` belongs to that project and never goes back to the kit.

## Rule 1: factory changes and product changes never share a commit

A factory change touches a protected path, so in a project it already needs its own pull request with the label `human-judge-change`. Keep that pull request to factory files only. If a ticket needs both, make two pull requests.

## Rule 2: a human makes factory changes

The agent that runs laps may not edit these files, and the fence stops it. Make the change yourself, or in a separate agent session that you direct and review, on a branch named `factory/<short-name>`. Never during a lap.

## Rule 3: every factory change is written down

Add an entry to `CHANGELOG.md` in the same commit: what went wrong, in which project and lap, and what changed. A change with no observed problem behind it is usually not worth making.

## Where to make the change

| Situation | Make it in | Then |
|---|---|---|
| A lap in a project showed a problem (most cases) | That project, so you can re-run the lap and see it fixed | Carry it to the kit |
| An idea with no project involved, or a change to the kit's own documents | The kit | Carry it to projects when they need it |

## Carrying a change from a project to the kit

One-time, in the project clone:

```bash
git remote add kit https://<host>/<owner>/factory-kit.git   # <host>: github.com or your GitHub Enterprise host
# or, if the kit exists only as a local clone: git remote add kit <path to factory-kit>
```

For each factory change, after its pull request merged in the project:

```bash
git fetch kit
git switch -c kit-port kit/main
git cherry-pick <commit of the factory change>
git push kit kit-port:port/<short-name>
git switch main && git branch -D kit-port
```

Then open the pull request `port/<short-name>` → `main` in the kit; the agent may open it with `gh`. A human merges it.

Check two things before you push:

1. **No project names.** The kit uses the placeholders `__OWNER__`, `__PROJECT__`, `__PARENT_DIR__` and `__HOST__`. If the change touched a line that holds a real name in the project (`.github/CODEOWNERS`, `.claude/settings.json`, `RUNBOOK.md`, `README.md`), put the placeholder back.
2. **No product.** `git show --stat` must list factory files only.

If the pull request was squash-merged, cherry-pick the squashed commit on `main`.

## Carrying a change from the kit to a project

```bash
git fetch kit
git switch -c factory/update-from-kit
git cherry-pick <kit commit>        # or several
git push -u origin factory/update-from-kit
```

Open the pull request in the project; the agent may open it with `gh`. A human adds the label `human-judge-change` and merges when the checks are green. Replace placeholders with the project's real names where the change touched such a line.

## Changes that need extra care

| Change | Why | Do this as well |
|---|---|---|
| `harness/run-gates.sh`, or anything that makes a gate easier to pass | It weakens the judge | Run `bash harness/calibrate.sh` before and after. Every defect must still be `CAUGHT`. |
| `.github/workflows/judge-guards.yml` | It uses `pull_request_target`, which has access to secrets | Never add a step that checks out or runs pull request code. |
| The protected-path list | It appears in five places | Change all five together: `FACTORY_RULES.md` section 2, `.claude/settings.json`, `.kiro/agents/factory.json` (in the kit: `fence/claude-settings.json`, `fence/kiro-factory.json`), `.github/CODEOWNERS`, and the `protected-paths` pattern in `harness/judge/guards.json` (read by both `judge-guards.yml` and the factory judge). |
| `harness/runtime/verify.py` or `verifier.md` | They decide whether the running app does what the ticket says | Run `python -m unittest discover -s harness/runtime`. Keep the scenario read from `main`, the checkout guard, and evidence as one file per assertion inside the attempt's folder. |
| `harness/judge/classify.py` patterns | A pattern that also matches a failure the change can cause lets the change escape the round budget | Add a pattern only for a machine failure seen in a real log, and add that log line to its test; also add a line the change can cause that it must not match. |
| `harness/judge/judge.py` | It runs pull request code where Actions is not allowed | Keep `harness/` taken from `main`, and no token in the gate's environment. Run `python -m unittest discover -s harness/judge`; its Git tests prove both. |
| `harness/judge/guards.json` or `guards.py` | The two guards, for the workflow and for the factory judge alike | Run `python -m unittest discover -s harness/judge`. The workflow must keep calling `guards.py` and hold no pattern of its own. |
| The `lap` skill | Each agent reads its own copy | Change `.claude/skills/lap/SKILL.md`, then copy it to `.kiro/skills/lap/SKILL.md`. The `gates` workflow fails while the two differ. |
| The agent instructions | Claude Code and Kiro read one file | Change `AGENTS.md`. `CLAUDE.md` only imports it (`@AGENTS.md`); keep it that way. |
| The runtime contract in `harness/README.md` | Gates and BMAD's architect rely on it | Update `harness/run-gates.sh` and `_bmad/custom/bmad-architecture.toml` if they mention the item. |
| `harness/rounds.json` or `harness/board/lap_round.py` | The budget is what keeps a lap's cost bounded | Run `python -m unittest discover -s harness/board` and `-s harness/dispatch`. A new kind of check that can send work back adds a source here, not a limit of its own. |
| `_bmad/custom/*.toml` | BMAD merges these with its defaults | Check with `uv run --no-cache _bmad/scripts/resolve_customization.py --skill .claude/skills/<skill> --project-root . --key workflow` (or `--key agent`). |
| How a new project is set up | The steps exist in two forms: for a person and for an agent | Change `AGENT_SETUP.md` and the one-time setup in `RUNBOOK.md` together. Do not put steps in the README prompt; it only points to `AGENT_SETUP.md`. |
| A BMAD upgrade | Skill names and customisation keys can change | Upgrade in one project first, run a lap, then update `skills-lock.json` in the kit. |

## What not to change in a project

- BMAD's own files under `.claude/skills/bmad*` and `_bmad/` (except `_bmad/custom/`). They are overwritten on every BMAD update. Use `_bmad/custom/`.
- The factory files during a lap, to get a red check green. If a check is wrong, stop the lap, fix the check as a factory change, then start the lap again.
