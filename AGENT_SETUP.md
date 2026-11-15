# Instructions for the agent: set up a new project from this kit

You are an agent asked to create a new software-factory project. The person gave you three values:

- **OWNER** — the GitHub user or organisation that owns the kit and will own the new repositories
- **PROJECT** — the new project's name, lower-case-with-dashes
- **DIRECTORY** — the local folder where both repositories are cloned, side by side

Do every step in order. After each step, run its checks. Stop and report if a step fails and you cannot fix its cause; never skip a step or a check.

This file is the single source for setup. If the person's prompt and this file disagree on a step, follow this file and say so in your report. Rules the person adds in their prompt always apply on top.

## Background

The kit is two private GitHub template repositories: `OWNER/factory-kit` (the application side) and `OWNER/factory-kit-holdouts` (hidden acceptance tests). A project is one copy of each: `PROJECT` and `PROJECT-holdouts`. Once each clone exists, read its `README.md`, and in the application clone also `RUNBOOK.md` and `MODIFYING.md`, before changing anything.

## Rules

- Never create, ask for, print or store a token, password or secret. Those steps belong to the person.
- Do not change any factory file by hand: `FACTORY_RULES.md`, `CLAUDE.md`, `harness/`, `.github/`, `_bmad/custom/`, `.claude/settings.json`, `.claude/skills/lap/`. The only allowed change to them is what `init-project.sh` does.
- Setup only. Do not write `MISSION.md` content, a PRD, tickets, application code, or any hidden scenario.
- Use HTTPS remotes (`https://github.com/OWNER/<repo>.git`). If a clone or push fails on SSH, switch the remote to HTTPS and retry.
- End every commit message with the co-author line your environment tells you to use.
- Run from a session opened in DIRECTORY, not inside an existing factory project: that project's fence would block this setup. If you find yourself blocked by a fence, stop and tell the person.

## Step 1: Preflight

- Run `git --version`, `gh auth status`, `node --version`, `uv --version`. Stop if one is missing or `gh` lacks the `repo` or `workflow` scope.
- Confirm both templates exist: `gh repo view OWNER/factory-kit --json isTemplate` and the same for `OWNER/factory-kit-holdouts`.
- Confirm `OWNER/PROJECT` and `OWNER/PROJECT-holdouts` do **not** exist on GitHub, and that DIRECTORY has no folder named `PROJECT` or `PROJECT-holdouts`. If any exists, stop and ask.

## Step 2: Create and clone both repositories

```bash
gh repo create OWNER/PROJECT --private --template OWNER/factory-kit
gh repo create OWNER/PROJECT-holdouts --private --template OWNER/factory-kit-holdouts
```

A template copy takes a few seconds. Wait until each repository has a `main` branch, then clone both into DIRECTORY over HTTPS.

**Check:** both folders exist, each on `main`, each with the kit's files.

## Step 3: Fill in the placeholders

```bash
# in PROJECT
bash init-project.sh OWNER PROJECT
# in PROJECT-holdouts
bash init-project.sh PROJECT
```

**Check:**
- No file contains a placeholder (two underscores, then `OWNER`, `PROJECT` or `PARENT_DIR`, then two underscores), except `README.md`, `MODIFYING.md`, `CHANGELOG.md` and this file.
- Both `init-project.sh` files are gone.
- The JSON file in `PROJECT/.claude/` parses, and its deny list names `PROJECT-holdouts`.

Commit in each repository ("Fill in project names") and push.

## Step 4: Install and set up BMAD v7 (in PROJECT only)

```bash
npx -y skills add bmad-code-org/BMAD-METHOD/skills/core-tools --skill '*' -a claude-code -y
npx -y skills add bmad-code-org/BMAD-METHOD/skills/method --skill '*' -a claude-code -y
uv run --no-cache .claude/skills/bmad/scripts/setup.py --project-root . --skill .claude/skills/bmad --root .claude/skills
```

The setup command prints JSON. It must show `"current": true` and an empty `"problems"` list. If it lists pending questions, ask the person; do not invent answers.

**Check** that the factory's BMAD rules are picked up:

```bash
uv run --no-cache _bmad/scripts/resolve_customization.py --skill .claude/skills/bmad-build --project-root . --key workflow
```

The output must contain the review lens id `factory-judge`, `"review": "thorough"`, and `MISSION.md` among `persistent_facts`. Also check that `.claude/skills/lap/SKILL.md` still exists and is unchanged (`git status` shows it clean).

Commit ("Install BMAD v7") and push. Include `.claude/skills/`, `_bmad/` and `skills-lock.json`.

## Step 5: GitHub settings that need no secret

```bash
gh variable set HOLDOUTS_REPO --repo OWNER/PROJECT --body OWNER/PROJECT-holdouts
gh variable set APP_REPO --repo OWNER/PROJECT-holdouts --body OWNER/PROJECT
gh label create human-judge-change --repo OWNER/PROJECT
gh label create human-approved-irreversible --repo OWNER/PROJECT
```

Kit remotes, for carrying factory changes later (see `MODIFYING.md`):

```bash
# in PROJECT
git remote add kit https://github.com/OWNER/factory-kit.git && git fetch kit
# in PROJECT-holdouts
git remote add kit https://github.com/OWNER/factory-kit-holdouts.git && git fetch kit
```

**Check:** `gh variable list` and `gh label list` show them; `git remote -v` shows `kit` in both clones.

## Step 6: Check the judge runs

- In `PROJECT`: `bash harness/run-gates.sh` must exit 0 and print `NOTICE: no backend yet, nothing to judge.`
- In `PROJECT-holdouts`: `bash run-judges.sh ../PROJECT` must exit 0 and write `no-app` to `result.txt`. Delete `result.txt` afterwards.
- On GitHub: `gh workflow run gates --repo OWNER/PROJECT` and `gh workflow run calibrate --repo OWNER/PROJECT`. Wait for both and confirm the conclusion is `success`. If one fails, show the failing step's log.

## Step 7: Branch protection (try, do not force)

Try to protect `main` in `OWNER/PROJECT` through the GitHub API: require a pull request; required status checks `gates`, `protected-paths`, `scope-guard` and `holdouts`; 0 required approvals. If GitHub refuses (for example a free plan with a private repository), do not work around it. Report it as open.

## Step 8: Report

Give the person a short report:

1. Links to both repositories and the two local folder paths.
2. A table of steps 1–7: done, failed or open, one line each, with evidence (commit ids, workflow run links).
3. What is left for them, with exact instructions:
   - Create two fine-grained tokens and store them as secrets (the tokens step in `RUNBOOK.md`): `HOLDOUTS_DISPATCH_TOKEN` in `PROJECT`, `APP_REPO_TOKEN` in `PROJECT-holdouts`.
   - Branch protection, if step 7 is open.
   - In a **new** session opened inside `PROJECT`: ask it to edit `MISSION.md` and confirm it is refused. That proves the fence is active.
   - Plan the product with BMAD, fill in `MISSION.md` themselves, write hidden scenarios in a separate session opened in `PROJECT-holdouts`, then say "run a lap".
4. Anything that surprised you, or that this file or the kit's other documents got wrong, so the kit can be fixed.

Then tell the person to close this session. Laps run in a fresh session opened inside the project folder, so the fence applies.
