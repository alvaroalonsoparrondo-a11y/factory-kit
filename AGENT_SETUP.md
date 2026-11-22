# Instructions for the agent: set up a new project from this kit

You are an agent asked to create a new software-factory project. The person gave you three values:

- **OWNER** — the GitHub user or organisation that owns the kit and will own the new repository
- **PROJECT** — the new project's name, lower-case-with-dashes
- **DIRECTORY** — the local folder where the repository is cloned

They may also give these; otherwise use the default:

- **HOST** — the GitHub host. Default `github.com`; a GitHub Enterprise host such as `github.example.com` otherwise. If the person gives a repository URL, its host is HOST.
- **KIT** — a local clone of the kit. Default: clone `HOST/OWNER/factory-kit` into `DIRECTORY/factory-kit` (or use that folder if it is already a clone of it). The person may name another folder.
- **AGENTS** — which agents the project is set up for: `claude-code`, `kiro-cli`, or both. Default both.

If the person gives a repository URL whose name differs from PROJECT, or a value that contradicts another, stop and ask which one holds.

Do every step in order. After each step, run its checks. Stop and report if a step fails and you cannot fix its cause; never skip a step or a check.

This file is the single source for setup. If the person's prompt and this file disagree on a step, follow this file and say so in your report. Rules the person adds in their prompt always apply on top.

## Background

The kit is the GitHub repository `OWNER/factory-kit`. It is not a template: a project starts as an empty repository, and the kit's tool `bin/kit.py` installs the factory into it (`kit.py init`) and later updates it (`kit.py sync`). The kit's `template/` folder holds the files it keeps up to date in every project, `seed/` the files a project starts with. Read the kit's `README.md`, and in it `template/RUNBOOK.md` and `template/MODIFYING.md`, before changing anything.

Name repositories to `gh` as `HOST/OWNER/<repo>` (for example `gh repo view HOST/OWNER/PROJECT`), and call the API as `gh api --hostname HOST ...`, so every command reaches HOST even when `gh` is signed in to more than one.

## Rules

- Never create, ask for, print or store a token, password or secret. Those steps belong to the person.
- Do not change any factory file by hand: `FACTORY_RULES.md`, `AGENTS.md`, `CLAUDE.md`, `harness/`, `.github/`, `_bmad/custom/`, `.claude/settings.json`, `.claude/skills/lap/`, `.kiro/agents/`, `.kiro/skills/lap/`. The only allowed change to them is what `kit.py init` writes.
- Setup only. Do not write `MISSION.md` content, a PRD, tickets or application code.
- Do not change organisation or repository policy to make a step pass: do not switch on GitHub Actions, change a repository's visibility, or add runners. Report the step as open instead.
- Use HTTPS remotes (`https://HOST/OWNER/<repo>.git`). If a clone or push fails on SSH, switch the remote to HTTPS and retry.
- If your environment gives you a co-author line, end every commit message with it. If it gives none, add none, and say so in your report.
- Run from a session opened in DIRECTORY, not inside an existing factory project: that project's rules would apply to this setup. If you find yourself blocked by a permission rule, stop and tell the person.

## Step 1: Preflight

- Run `git --version`, `gh auth status --hostname HOST`, `node --version`, `uv --version`. Stop if one is missing, `gh` is not signed in to HOST, or it lacks the `repo` or `workflow` scope.
- Get the kit: if KIT does not exist, `git clone https://HOST/OWNER/factory-kit.git KIT`. Then check:
  - `KIT/bin/kit.py` and `KIT/template/` exist;
  - `git -C KIT status --porcelain` is empty, and `main` is checked out and up to date with its `origin` (`git -C KIT pull --ff-only`);
  - note the commit: `git -C KIT log -1 --format=%h`.
- Confirm `HOST/OWNER/PROJECT` does **not** exist, and that DIRECTORY has no folder named `PROJECT`. If either exists, stop and ask.

## Step 2: Create and clone the repository

```bash
gh repo create HOST/OWNER/PROJECT --private
git clone https://HOST/OWNER/PROJECT.git DIRECTORY/PROJECT
```

The clone is empty; Git warns about that, which is expected. If its branch is not `main`, run `git -C DIRECTORY/PROJECT switch -c main`.

**Check:** the folder exists, on `main`, with no files yet.

## Step 3: Install the factory

```bash
# in PROJECT
python KIT/bin/kit.py --kit KIT init --owner OWNER --host HOST
python KIT/bin/kit.py --kit KIT doctor
```

`init` copies the kit's files, the fence and the seeds (`MISSION.md`, `README.md`, `PROJECT_NOTES.md`, `.github/CODEOWNERS`, `.claude/launch.json`), fills in the names in the seeds, and writes `kit.lock.json`.

**Check:**
- `doctor` prints `doctor: OK` (warnings are fine; read them).
- No file in PROJECT contains a placeholder: two underscores, then `OWNER`, `PROJECT` or `HOST`, then two underscores.
- `kit.lock.json` exists and its `revision` is the kit commit you noted in step 1.
- The JSON files `.claude/settings.json` and `.kiro/agents/factory.json` parse. The first has a non-empty deny list, the second a `deny` rule for `fs_write`: they are the fence that keeps Claude Code and Kiro out of the factory files. Check both whatever AGENTS is: they are factory files and stay in the project.

Commit ("Install the factory from the kit at <commit>") and push: `git push -u origin main`.

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
gh label create human-granted-round --repo HOST/OWNER/PROJECT
```

**Check:** `gh label list --repo HOST/OWNER/PROJECT` shows them.

## Step 6: Check the judge runs

- In `PROJECT`: `bash harness/run-gates.sh` must exit 0 and print `NOTICE: no backend yet, nothing to judge.`
- Check that GitHub Actions may run: `gh api --hostname HOST repos/OWNER/PROJECT/actions/permissions`. If it shows `"enabled": false`, stop this bullet: do not switch it on. Ask the person whether Actions is allowed at all. If it is not, the GitHub half of this step is open; go on to step 7 and say in your report that the project runs as in `RUNBOOK.md`, "Without GitHub Actions".
- On GitHub: pushes to `main` should already have started `gates` runs; confirm at least one succeeded. Then also `gh workflow run gates --repo HOST/OWNER/PROJECT` and `gh workflow run calibrate --repo HOST/OWNER/PROJECT`. Wait for both and confirm the conclusion is `success`. If one fails, show the failing step's log. If a run stays queued for more than ten minutes, no runner picks it up: report it as open.

## Step 7: Branch protection (try, do not force)

Try to protect `main` in `OWNER/PROJECT` through the API (`gh api --hostname HOST -X PUT repos/OWNER/PROJECT/branches/main/protection --input <file>`; write the JSON body to a file, because piping it through a Windows shell can garble it): require a pull request; 0 required approvals; required status checks `gates`, `protected-paths` and `scope-guard`.

- If step 6 found that Actions cannot run, leave out the required status checks: until the factory judge runs, they would never report, so no pull request could merge except by an admin bypassing the rule. Report the checks as open, to be required once the person runs the judge.
- If GitHub refuses (a free plan answers 403 "Upgrade to GitHub Pro or make this repository public" for a private repository), do not work around it. Report it as open.

## Step 8: Report

Give the person a short report:

1. The link to the repository, the local folder path, and the kit folder (KIT), which the project needs next to it for `kit.py sync`.
2. A table of steps 1–7: done, failed or open, one line each, with evidence (commit ids, workflow run links).
3. What is left for them, with exact instructions:
   - Branch protection, if step 7 is open.
   - Without Actions: each lap runs the factory judge on its own pull request (lap step A10); require the three checks once the first lap has posted them (`RUNBOOK.md`, "Without GitHub Actions"). The judge needs Java 21 and Node 22 on the machine where laps run.
   - Plan the product with BMAD, fill in `MISSION.md` themselves, then say "run a lap".
4. Anything that surprised you, or that this file or the kit's other documents got wrong, so the kit can be fixed.

Then tell the person to close this session. Laps run in a fresh session opened inside the project folder, so its `AGENTS.md` and rules apply (in Kiro: `kiro-cli chat --agent factory`).
