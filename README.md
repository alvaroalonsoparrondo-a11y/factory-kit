# Factory kit

A reusable software factory for BMAD v7: an agent builds one ticket per lap, and a judge the agent cannot change decides whether it merges.

This repository is a **template**. It holds only the factory, no product.

| Document | Read it when |
|---|---|
| [RUNBOOK.md](RUNBOOK.md) | You start a new project from this kit, or run laps in one |
| [AGENT_SETUP.md](AGENT_SETUP.md) | You are an agent setting up a new project (or you want to see what it will do) |
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
| Agent set-up | `AGENTS.md` (the instructions), `CLAUDE.md` (imports `AGENTS.md`), `.claude/settings.json` (permissions; the deny list is the fence), `.claude/skills/lap/` (the lap) | Claude Code |
| | `AGENTS.md`, `.kiro/agents/factory.json` (the agent; its deny rules are the fence), `.kiro/skills/lap/` (a copy of the lap, kept equal by `gates`) | Kiro CLI |
| Project plumbing | `.github/CODEOWNERS`, `.github/pull_request_template.md` | GitHub |

BMAD's own skills are **not** in the kit. Each project installs them, so the kit stays small and BMAD upgrades stay separate from factory changes.

## Start a new project

1. On GitHub: **Use this template** on `factory-kit` → `<project>`, private.
2. Clone it.
3. Run the one-time script `bash init-project.sh <github-owner> <project>` (add the host as a third value on GitHub Enterprise), then commit.
4. Follow [RUNBOOK.md](RUNBOOK.md).

## Start a new project with an agent

Instead of the manual steps above, hand the setup to an agent. The steps live in [AGENT_SETUP.md](AGENT_SETUP.md); the prompt only says who, what and where.

1. Open an agent session (Claude Code or Kiro CLI) in the **parent folder** where the new project should be cloned. Do not use a session opened inside an existing factory project: its rules would apply to the setup.
2. The machine needs `git`, `gh` (signed in, with the `repo` and `workflow` scopes), Node, `uv`, and Git Bash on Windows.
3. Fill in the three values and send this prompt. On GitHub Enterprise, add a `Host:` line and pass `--hostname <host>` to `gh api`. If the kit exists only as a local clone, add `Kit: <path to factory-kit>` and read `AGENT_SETUP.md` from that folder instead. To set up for one agent only, add `Agents: kiro-cli` (or `claude-code`).

~~~text
Set up a new software-factory project from my factory kit.

Owner: <github owner>
Project: <project-name>
Clone into: this folder

First read the setup instructions from the kit:
  gh api repos/<github owner>/factory-kit/contents/AGENT_SETUP.md -H "Accept: application/vnd.github.raw"
Then follow them exactly, step by step, including every check and the final report.

Never create or handle tokens or secrets; list those steps for me at the end.
Setup only: do not write the mission, a PRD, tickets or code.
~~~

Add your own rules as extra lines at the end of the prompt. To change how setup works for everyone, change `AGENT_SETUP.md` (see [MODIFYING.md](MODIFYING.md)), not the prompt.

After the agent finishes, close that session. Laps always run in a fresh session opened inside the project folder, so its `AGENTS.md` and rules apply.

## Status

Tested so far: an agent-style setup of a throwaway project end to end; `gates` and `calibrate` on GitHub; the two guard checks on a real pull request. Not yet tested: a full lap. See [CHANGELOG.md](CHANGELOG.md).

Kiro CLI: interactive laps are set up (`AGENTS.md`, `.kiro/agents/factory.json`, `.kiro/skills/lap/`) but not yet tested in a real lap. Planned: headless Kiro laps in the dispatcher, and AWS CodeBuild versions of the workflows.
