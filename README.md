# Factory kit

A reusable software factory for BMAD v7: an agent builds one ticket per lap, and a judge the agent cannot change decides whether it merges.

This repository is **the kit**. It holds only the factory, no product. Its tool `bin/kit.py` installs the factory into a project and keeps it up to date.

| Document | Read it when |
|---|---|
| [template/RUNBOOK.md](template/RUNBOOK.md) | You start a new project from this kit, or run laps in one |
| [AGENT_SETUP.md](AGENT_SETUP.md) | You are an agent setting up a new project (or you want to see what it will do) |
| [template/MODIFYING.md](template/MODIFYING.md) | You want to change the factory, or take an update into a project |
| [CHANGELOG.md](CHANGELOG.md) | You want to know what changed in the kit and why |
| [template/FACTORY_RULES.md](template/FACTORY_RULES.md) | You want the rules the agent works under |
| [template/harness/README.md](template/harness/README.md) | You want the contract an application must keep so it can be judged |
| [The design](docs/superpowers/specs/2026-11-22-kit-sync-design.md) | You want to know why the kit is laid out this way |

## What is in the kit

| Folder | What it is | What `kit.py` does with it |
|---|---|---|
| `template/` | The files the kit owns, at the path a project has them: the rules, the judge (`harness/`, `.github/workflows/`), BMAD rules (`_bmad/custom/`), the agent set-up (`AGENTS.md`, `CLAUDE.md`, the `lap` skill for Claude Code and Kiro) and the fence (`.claude/settings.json`, `.kiro/agents/factory.json`) | `init` copies them; `sync` keeps them up to date. The fence is merged, so a project may add its own deny rules |
| `seed/` | The files a project starts with and then owns: `MISSION.md`, `README.md`, `PROJECT_NOTES.md`, `.github/CODEOWNERS`, `.claude/launch.json` | `init` copies them once, with the project's names filled in |
| `bin/` | `kit.py`, its tests, and `kit.json` (the kit's phase: young or mature) | |
| the rest | This README, `AGENT_SETUP.md`, `CHANGELOG.md`, `docs/`, and the kit's own `CLAUDE.md`, settings and CI | Never copied |

The fence is **off in the kit itself**, so you and agents you direct may change the factory here. It is on in every project.

BMAD's own skills are **not** in the kit. Each project installs them (see `template/RUNBOOK.md`), so the kit stays small and BMAD upgrades stay separate from factory changes.

## Start a new project

1. Create an empty private repository `<project>` on GitHub (or GitHub Enterprise) and clone it.
2. Clone `factory-kit` into the same parent folder, next to it.
3. From the project's folder: `python ../factory-kit/bin/kit.py init --owner <user or team>`, then commit and push.
4. Follow `RUNBOOK.md` in the project.

## Update a project

From the project's folder, with the kit clone next to it and up to date:

```bash
python ../factory-kit/bin/kit.py status   # what the kit has that the project does not
python ../factory-kit/bin/kit.py sync     # takes it, on a new branch factory/sync-<revision>
```

`sync` writes fenced files, so a person runs it. It commits nothing and prints a pull request body; open the pull request, add `human-judge-change`, and merge when the checks are green. See `template/MODIFYING.md`.

## Start a new project with an agent

Instead of the manual steps above, hand the setup to an agent. The steps live in [AGENT_SETUP.md](AGENT_SETUP.md); the prompt only says who, what and where.

1. Open an agent session (Claude Code or Kiro CLI) in the **parent folder** where the new project should be cloned. Do not use a session opened inside an existing factory project: its rules would apply to the setup.
2. The machine needs `git`, `gh` (signed in, with the `repo` and `workflow` scopes), Node, `uv`, and Git Bash on Windows.
3. Fill in the three values and send this prompt. On GitHub Enterprise, add a `Host:` line and pass `--hostname <host>` to `gh api`. If you already have a clone of the kit, add `Kit: <path to factory-kit>` and read `AGENT_SETUP.md` from that folder instead. To set up for one agent only, add `Agents: kiro-cli` (or `claude-code`).

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
