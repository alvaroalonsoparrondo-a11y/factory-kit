# Factory kit

A reusable software factory for BMAD v7: an agent builds one ticket per lap, and a judge the agent cannot see or change decides whether it merges.

This repository is a **template**. It holds only the factory, no product. Its partner template, `factory-kit-holdouts`, holds the hidden acceptance tests.

| Document | Read it when |
|---|---|
| [RUNBOOK.md](RUNBOOK.md) | You start a new project from this kit, or run laps in one |
| [MODIFYING.md](MODIFYING.md) | You want to change the factory itself |
| [CHANGELOG.md](CHANGELOG.md) | You want to know what changed in the kit and why |
| [FACTORY_RULES.md](FACTORY_RULES.md) | You want the rules the agent works under |
| [harness/README.md](harness/README.md) | You want the contract an application must keep so it can be judged |

## What is in the kit

| Part | Files | Tied to |
|---|---|---|
| Constitution and rules | `MISSION.md` (template), `FACTORY_RULES.md` | nothing |
| The judge | `harness/`, `.github/workflows/` | Spring + Angular + Playwright; GitHub Actions |
| BMAD rules | `_bmad/custom/`, `skills-lock.json` | BMAD v7 |
| Agent set-up | `CLAUDE.md`, `.claude/settings.json` (the fence), `.claude/skills/lap/` (the lap) | Claude Code |
| Project plumbing | `.github/CODEOWNERS`, `.github/pull_request_template.md` | GitHub |

BMAD's own skills are **not** in the kit. Each project installs them, so the kit stays small and BMAD upgrades stay separate from factory changes.

## Start a new project

1. On GitHub: **Use this template** on `factory-kit` → `<project>`, and on `factory-kit-holdouts` → `<project>-holdouts`. Both private.
2. Clone both next to each other.
3. In each clone, run the one-time script, then commit:
   - `bash init-project.sh <github-owner> <project>` in the application repository
   - `bash init-project.sh <project>` in the hidden-scenario repository
4. Follow [RUNBOOK.md](RUNBOOK.md).

## Status

Tested so far: scripts and workflows parse; `gates` and `calibrate` pass on GitHub with no application present. Not yet tested: a full lap, the pull request checks, the hidden-scenario judge. See [CHANGELOG.md](CHANGELOG.md).

Planned: Kiro versions of the three agent set-up files (`.kiro/steering/`, `.kiro/agents/`), and AWS CodeBuild versions of the workflows.
