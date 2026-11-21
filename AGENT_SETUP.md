# Instructions for the agent: set up a new project from this kit

You are an agent asked to create a new software-factory project. The person gave you three values:

- **OWNER** — the GitHub user or organisation that owns the kit and will own the new repository
- **PROJECT** — the new project's name, lower-case-with-dashes
- **DIRECTORY** — the local folder where the repository is cloned

They may also give these; otherwise use the default:

- **HOST** — the GitHub host. Default `github.com`; a GitHub Enterprise host such as `github.example.com` otherwise. If the person gives a repository URL, its host is HOST.
- **KIT** — where the kit comes from. Default the template repository `HOST/OWNER/factory-kit`; or a local folder holding a clone of the kit.
- **AGENTS** — which agents the project is set up for: `claude-code`, `kiro-cli`, or both. Default both.

If the person gives a repository URL whose name differs from PROJECT, or a value that contradicts another, stop and ask which one holds.

Do every step in order. After each step, run its checks. Stop and report if a step fails and you cannot fix its cause; never skip a step or a check.

This file is the single source for setup. If the person's prompt and this file disagree on a step, follow this file and say so in your report. Rules the person adds in their prompt always apply on top.

## Background

The kit is a private GitHub template repository, `OWNER/factory-kit`, or a local clone of it. A project is one copy of it: `PROJECT`. Once the clone exists, read its `README.md`, `RUNBOOK.md` and `MODIFYING.md` before changing anything.

Name repositories to `gh` as `HOST/OWNER/<repo>` (for example `gh repo view HOST/OWNER/PROJECT`), and call the API as `gh api --hostname HOST ...`, so every command reaches HOST even when `gh` is signed in to more than one.

## Rules

- Never create, ask for, print or store a token, password or secret. Those steps belong to the person.
- Do not change any factory file by hand: `FACTORY_RULES.md`, `AGENTS.md`, `CLAUDE.md`, `harness/`, `.github/`, `_bmad/custom/`, `.claude/settings.json`, `.claude/skills/lap/`, `.kiro/agents/`, `.kiro/skills/lap/`. The only allowed change to them is what `init-project.sh` does.
- Setup only. Do not write `MISSION.md` content, a PRD, tickets or application code.
- Do not change organisation or repository policy to make a step pass: do not switch on GitHub Actions, change a repository's visibility, or add runners. Report the step as open instead.
- Use HTTPS remotes (`https://HOST/OWNER/<repo>.git`). If a clone or push fails on SSH, switch the remote to HTTPS and retry.
- If your environment gives you a co-author line, end every commit message with it. If it gives none, add none, and say so in your report.
- Run from a session opened in DIRECTORY, not inside an existing factory project: that project's rules would apply to this setup. If you find yourself blocked by a permission rule, stop and tell the person.

## Step 1: Preflight

- Run `git --version`, `gh auth status --hostname HOST`, `node --version`, `uv --version`. Stop if one is missing, `gh` is not signed in to HOST, or it lacks the `repo` or `workflow` scope.
- Confirm the kit exists:
  - template: `gh repo view HOST/OWNER/factory-kit --json isTemplate` shows `"isTemplate": true`;
  - local folder: `git -C KIT status` works, and note the commit of its `main` (`git -C KIT log -1 --format=%h main`). Use `main`, whatever branch is checked out there.
- Confirm `HOST/OWNER/PROJECT` does **not** exist, and that DIRECTORY has no folder named `PROJECT`. If either exists, stop and ask.

## Step 2: Create and clone the repository

From a template:

```bash
gh repo create HOST/OWNER/PROJECT --private --template HOST/OWNER/factory-kit
```

A template copy takes a few seconds. Wait until the repository has a `main` branch.

From a local folder (there is no template to copy, so the kit's `main` is pushed into an empty repository):

```bash
gh repo create HOST/OWNER/PROJECT --private
git -C KIT push https://HOST/OWNER/PROJECT.git main:main
```

The project then starts with the kit's history instead of one fresh commit; that is expected. Push only `main`, never the kit's other branches.

Then clone it into DIRECTORY over HTTPS.

**Check:** the folder exists, on `main`, with the kit's files.

## Step 3: Fill in the placeholders

```bash
# in PROJECT
bash init-project.sh OWNER PROJECT HOST
```

**Check:**
- No file contains a placeholder (two underscores, then `OWNER`, `PROJECT`, `PARENT_DIR` or `HOST`, then two underscores), except `MODIFYING.md`, which explains them.
- `init-project.sh` is gone. `README.md` is now a short project page, and the kit-only files `AGENT_SETUP.md`, `CHANGELOG.md` and `PROJECT_README.md` are gone, and so is `fence/` (its settings are now in place). Keep following the copy of these instructions you already read.
- The JSON files `PROJECT/.claude/settings.json` and `PROJECT/.kiro/agents/factory.json` parse. The first has a non-empty deny list, the second a `deny` rule for `fs_write`: they are the fence that keeps Claude Code and Kiro out of the factory files. Check both whatever AGENTS is: they are factory files and stay in the project.

Commit ("Fill in project names") and push.

## Step 4: Install and set up BMAD v7 (in PROJECT only)

Install for the agents in AGENTS only: one `-a` per agent (`-a claude-code`, `-a kiro-cli`).

```bash
npx -y skills add bmad-code-org/BMAD-METHOD/skills/core-tools --skill '*' -a claude-code -a kiro-cli -y
npx -y skills add bmad-code-org/BMAD-METHOD/skills/method --skill '*' -a claude-code -a kiro-cli -y
uv run --no-cache SKILLS/bmad/scripts/setup.py --project-root . --skill SKILLS/bmad --root SKILLS
```

`SKILLS` is `.claude/skills` when AGENTS includes `claude-code`, else `.kiro/skills`.

The setup command prints JSON. It must show `"current": true` and an empty `"problems"` list (`"status"` may be `created` or `repaired`; both are fine). If it lists pending questions, ask the person; do not invent answers. Note the `version` it reports for your report.

**Check** that the factory's BMAD rules are picked up:

```bash
uv run --no-cache _bmad/scripts/resolve_customization.py --skill SKILLS/bmad-build --project-root . --key workflow
```

The output must contain the review lens id `factory-judge`, `"review": "thorough"`, and `MISSION.md` among `persistent_facts`. Also check that `.claude/skills/lap/SKILL.md` and `.kiro/skills/lap/SKILL.md` still exist and are unchanged (`git status` shows them clean). With both agents, `.kiro/skills/` holds the same BMAD skills as `.claude/skills/`; with one, the other agent's folder holds only `lap`.

Commit ("Install BMAD v7") and push. Include the skill folders you installed into, `_bmad/` and `skills-lock.json`; stage them by name, not with `git add -A`.

## Step 5: GitHub settings that need no secret

```bash
gh label create human-judge-change --repo HOST/OWNER/PROJECT
gh label create human-approved-irreversible --repo HOST/OWNER/PROJECT
```

Kit remote, for carrying factory changes later (see `MODIFYING.md`):

```bash
# in PROJECT
git remote add kit https://HOST/OWNER/factory-kit.git && git fetch kit   # from a template
git remote add kit KIT && git fetch kit                                  # from a local folder
```

**Check:** `gh label list --repo HOST/OWNER/PROJECT` shows them; `git remote -v` shows `kit`.

## Step 6: Check the judge runs

- In `PROJECT`: `bash harness/run-gates.sh` must exit 0 and print `NOTICE: no backend yet, nothing to judge.`
- Check that GitHub Actions may run: `gh api --hostname HOST repos/OWNER/PROJECT/actions/permissions`. If it shows `"enabled": false`, stop this bullet: do not switch it on. Ask the person whether Actions is allowed at all. If it is not, the GitHub half of this step is open; go on to step 7 and say in your report that the project runs as in `RUNBOOK.md`, "Without GitHub Actions".
- On GitHub: pushes to `main` should already have started `gates` runs; confirm at least one succeeded. Then also `gh workflow run gates --repo HOST/OWNER/PROJECT` and `gh workflow run calibrate --repo HOST/OWNER/PROJECT`. Wait for both and confirm the conclusion is `success`. If one fails, show the failing step's log. If a run stays queued for more than ten minutes, no runner picks it up: report it as open.

## Step 7: Branch protection (try, do not force)

Try to protect `main` in `OWNER/PROJECT` through the API (`gh api --hostname HOST -X PUT repos/OWNER/PROJECT/branches/main/protection --input <file>`; write the JSON body to a file, because piping it through a Windows shell can garble it): require a pull request; 0 required approvals; required status checks `gates`, `protected-paths` and `scope-guard`.

- If step 6 found that Actions cannot run, leave out the required status checks: they would never report, so no pull request could merge except by an admin bypassing the rule. Report the checks as open.
- If GitHub refuses (a free plan answers 403 "Upgrade to GitHub Pro or make this repository public" for a private repository), do not work around it. Report it as open.

## Step 8: Report

Give the person a short report:

1. The link to the repository and the local folder path.
2. A table of steps 1–7: done, failed or open, one line each, with evidence (commit ids, workflow run links).
3. What is left for them, with exact instructions:
   - Branch protection, if step 7 is open.
   - Without Actions: the checks they run themselves before each merge (`RUNBOOK.md`, "Without GitHub Actions").
   - Plan the product with BMAD, fill in `MISSION.md` themselves, then say "run a lap".
4. Anything that surprised you, or that this file or the kit's other documents got wrong, so the kit can be fixed.

Then tell the person to close this session. Laps run in a fresh session opened inside the project folder, so its `AGENTS.md` and rules apply (in Kiro: `kiro-cli chat --agent factory`).
