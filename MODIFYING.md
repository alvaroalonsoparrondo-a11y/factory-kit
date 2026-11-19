# How to change the factory

The factory is improved while it is used. This page says where a change is made, how it reaches the kit, and how it reaches other projects.

## The two kinds of repository

- **The kit** (`factory-kit`): the source of truth for the factory. No product code.
- **A project** (for example `factory-pilot`): made from the kit. It holds a product plus a copy of the factory files.

The factory files have the same paths in both. That is what makes a change easy to carry across.

**Factory files** — a change to any of these is a factory change:

```
FACTORY_RULES.md   CLAUDE.md   RUNBOOK.md   MODIFYING.md   AGENT_SETUP.md
harness/           .github/    _bmad/custom/
.claude/settings.json          .claude/skills/lap/
```

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
git remote add kit https://github.com/<owner>/factory-kit.git
```

For each factory change, after its pull request merged in the project:

```bash
git fetch kit
git switch -c kit-port kit/main
git cherry-pick <commit of the factory change>
git push kit kit-port:port/<short-name>
git switch main && git branch -D kit-port
```

Then open the pull request `port/<short-name>` → `main` in the kit and merge it.

Check two things before you push:

1. **No project names.** The kit uses the placeholders `__OWNER__`, `__PROJECT__` and `__PARENT_DIR__`. If the change touched a line that holds a real name in the project (`.github/CODEOWNERS`, `.claude/settings.json`, `RUNBOOK.md`), put the placeholder back.
2. **No product.** `git show --stat` must list factory files only.

If the pull request was squash-merged, cherry-pick the squashed commit on `main`.

## Carrying a change from the kit to a project

```bash
git fetch kit
git switch -c factory/update-from-kit
git cherry-pick <kit commit>        # or several
git push -u origin factory/update-from-kit
```

Open the pull request in the project, add the label `human-judge-change`, and merge when the checks are green. Replace placeholders with the project's real names where the change touched such a line.

## Changes that need extra care

| Change | Why | Do this as well |
|---|---|---|
| `harness/run-gates.sh`, or anything that makes a gate easier to pass | It weakens the judge | Run `bash harness/calibrate.sh` before and after. Every defect must still be `CAUGHT`. |
| `.github/workflows/judge-guards.yml` | It uses `pull_request_target`, which has access to secrets | Never add a step that checks out or runs pull request code. |
| The protected-path list | It appears in four places | Change all four together: `FACTORY_RULES.md` section 2, `.claude/settings.json`, `.github/CODEOWNERS`, and the pattern in `judge-guards.yml`. |
| The runtime contract in `harness/README.md` | Gates and BMAD's architect rely on it | Update `harness/run-gates.sh` and `_bmad/custom/bmad-architecture.toml` if they mention the item. |
| `_bmad/custom/*.toml` | BMAD merges these with its defaults | Check with `uv run --no-cache _bmad/scripts/resolve_customization.py --skill .claude/skills/<skill> --project-root . --key workflow` (or `--key agent`). |
| How a new project is set up | The steps exist in two forms: for a person and for an agent | Change `AGENT_SETUP.md` and the one-time setup in `RUNBOOK.md` together. Do not put steps in the README prompt; it only points to `AGENT_SETUP.md`. |
| A BMAD upgrade | Skill names and customisation keys can change | Upgrade in one project first, run a lap, then update `skills-lock.json` in the kit. |

## What not to change in a project

- BMAD's own files under `.claude/skills/bmad*` and `_bmad/` (except `_bmad/custom/`). They are overwritten on every BMAD update. Use `_bmad/custom/`.
- The factory files during a lap, to get a red check green. If a check is wrong, stop the lap, fix the check as a factory change, then start the lap again.
