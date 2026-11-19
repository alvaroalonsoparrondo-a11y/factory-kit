# Instructions for the agent: set up a new project from this kit

You are an agent asked to create a new software-factory project. The person gave you three values:

- **OWNER** — the GitHub user or organisation that owns the kit and will own the new repository
- **PROJECT** — the new project's name, lower-case-with-dashes
- **DIRECTORY** — the local folder where the repository is cloned

Do every step in order. After each step, run its checks. Stop and report if a step fails and you cannot fix its cause; never skip a step or a check.

This file is the single source for setup. If the person's prompt and this file disagree on a step, follow this file and say so in your report. Rules the person adds in their prompt always apply on top.

## Background

The kit is a private GitHub template repository, `OWNER/factory-kit`. A project is one copy of it: `PROJECT`. Once the clone exists, read its `README.md`, `RUNBOOK.md` and `MODIFYING.md` before changing anything.

## Rules

- Never create, ask for, print or store a token, password or secret. Those steps belong to the person.
- Do not change any factory file by hand: `FACTORY_RULES.md`, `CLAUDE.md`, `harness/`, `.github/`, `_bmad/custom/`, `.claude/settings.json`, `.claude/skills/lap/`. The only allowed change to them is what `init-project.sh` does.
- Setup only. Do not write `MISSION.md` content, a PRD, tickets or application code.
- Use HTTPS remotes (`https://github.com/OWNER/<repo>.git`). If a clone or push fails on SSH, switch the remote to HTTPS and retry.
- End every commit message with the co-author line your environment tells you to use.
- Run from a session opened in DIRECTORY, not inside an existing factory project: that project's rules would apply to this setup. If you find yourself blocked by a permission rule, stop and tell the person.

## Step 1: Preflight

- Run `git --version`, `gh auth status`, `node --version`, `uv --version`. Stop if one is missing or `gh` lacks the `repo` or `workflow` scope.
- Confirm the template exists: `gh repo view OWNER/factory-kit --json isTemplate`.
- Confirm `OWNER/PROJECT` does **not** exist on GitHub, and that DIRECTORY has no folder named `PROJECT`. If either exists, stop and ask.

## Step 2: Create and clone the repository

```bash
gh repo create OWNER/PROJECT --private --template OWNER/factory-kit
```

A template copy takes a few seconds. Wait until the repository has a `main` branch, then clone it into DIRECTORY over HTTPS.

**Check:** the folder exists, on `main`, with the kit's files.

## Step 3: Fill in the placeholders

```bash
# in PROJECT
bash init-project.sh OWNER PROJECT
```

**Check:**
- No file contains a placeholder (two underscores, then `OWNER`, `PROJECT` or `PARENT_DIR`, then two underscores), except `MODIFYING.md`, which explains them.
- `init-project.sh` is gone. `README.md` is now a short project page, and the kit-only files `AGENT_SETUP.md`, `CHANGELOG.md` and `PROJECT_README.md` are gone. Keep following the copy of these instructions you already read.
- The JSON file in `PROJECT/.claude/` parses. Its deny list is empty: the fence is off, and the rules in `FACTORY_RULES.md` and `CLAUDE.md` bind the agent instead.

Commit ("Fill in project names") and push.

## Step 4: Install and set up BMAD v7 (in PROJECT only)

```bash
npx -y skills add bmad-code-org/BMAD-METHOD/skills/core-tools --skill '*' -a claude-code -y
npx -y skills add bmad-code-org/BMAD-METHOD/skills/method --skill '*' -a claude-code -y
uv run --no-cache .claude/skills/bmad/scripts/setup.py --project-root . --skill .claude/skills/bmad --root .claude/skills
```

The setup command prints JSON. It must show `"current": true` and an empty `"problems"` list (`"status"` may be `created` or `repaired`; both are fine). If it lists pending questions, ask the person; do not invent answers.

**Check** that the factory's BMAD rules are picked up:

```bash
uv run --no-cache _bmad/scripts/resolve_customization.py --skill .claude/skills/bmad-build --project-root . --key workflow
```

The output must contain the review lens id `factory-judge`, `"review": "thorough"`, and `MISSION.md` among `persistent_facts`. Also check that `.claude/skills/lap/SKILL.md` still exists and is unchanged (`git status` shows it clean).

Commit ("Install BMAD v7") and push. Include `.claude/skills/`, `_bmad/` and `skills-lock.json`.

## Step 5: GitHub settings that need no secret

```bash
gh label create human-judge-change --repo OWNER/PROJECT
gh label create human-approved-irreversible --repo OWNER/PROJECT
```

Kit remotes, for carrying factory changes later (see `MODIFYING.md`):

```bash
# in PROJECT
git remote add kit https://github.com/OWNER/factory-kit.git && git fetch kit
```

**Check:** `gh label list` shows them; `git remote -v` shows `kit`.

## Step 6: Check the judge runs

- In `PROJECT`: `bash harness/run-gates.sh` must exit 0 and print `NOTICE: no backend yet, nothing to judge.`
- On GitHub: pushes to `main` should already have started `gates` runs; confirm at least one succeeded. Then also `gh workflow run gates --repo OWNER/PROJECT` and `gh workflow run calibrate --repo OWNER/PROJECT`. Wait for both and confirm the conclusion is `success`. If one fails, show the failing step's log.

## Step 7: Branch protection (try, do not force)

Try to protect `main` in `OWNER/PROJECT` through the GitHub API: require a pull request; required status checks `gates`, `protected-paths` and `scope-guard`; 0 required approvals. If GitHub refuses (a free plan answers 403 "Upgrade to GitHub Pro or make this repository public" for a private repository), do not work around it. Report it as open.

## Step 8: Report

Give the person a short report:

1. The link to the repository and the local folder path.
2. A table of steps 1–7: done, failed or open, one line each, with evidence (commit ids, workflow run links).
3. What is left for them, with exact instructions:
   - Branch protection, if step 7 is open.
   - Plan the product with BMAD, fill in `MISSION.md` themselves, then say "run a lap".
4. Anything that surprised you, or that this file or the kit's other documents got wrong, so the kit can be fixed.

Then tell the person to close this session. Laps run in a fresh session opened inside the project folder, so its `CLAUDE.md` and rules apply.
