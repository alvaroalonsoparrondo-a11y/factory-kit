# Instructions for the agent: set up a new project from this kit

You are an agent asked to create a new software-factory project. The person gave you three values:

- **OWNER** — the GitHub user or organisation that owns the kit and will own the new repository
- **PROJECT** — the new project's name, lower-case-with-dashes
- **DIRECTORY** — the local folder where the repository is cloned

They may also give these; otherwise use the default:

- **HOST** — the GitHub host. Default `github.com`; a GitHub Enterprise host such as `github.example.com` otherwise. If the person gives a repository URL, its host is HOST.
- **KIT** — a local clone of the kit. Default: clone `HOST/OWNER/factory-kit` into `DIRECTORY/factory-kit` (or use that folder if it is already a clone of it). The person may name another folder.
- **AGENTS** — which agents the project is set up for: any combination of `claude-code`, `kiro-cli`, `copilot-cli`. Default `claude-code` and `kiro-cli`. Copilot supports supervised planning and triage only; a lap still needs Claude Code or Kiro.

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
- If AGENTS includes `copilot-cli`, check `copilot --version` (the integration was checked with 1.0.115). If missing, report that the human must install Copilot CLI. Copilot sign-in is separate from `gh`: ask the human to run `copilot login` if needed; never perform sign-in or handle its credentials for them.
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
```

`init` copies the kit's files, the fence and the seeds (`MISSION.md`, `README.md`, `PROJECT_NOTES.md`, `.github/CODEOWNERS`, `.claude/launch.json`), fills in the names in the seeds, and writes `kit.lock.json`. It then runs `doctor` itself, so do not run it again here; step 8 runs it once more, after BMAD and the GitHub settings.

**Check:**
- `init` exits 0 and its last line starts with `doctor: OK` (warnings are fine; read them). `open:` lines are expected at this point: BMAD, the labels and branch protection come in later steps.
- No file in PROJECT contains a placeholder: two underscores, then `OWNER`, `PROJECT` or `HOST`, then two underscores.
- `kit.lock.json` exists and its `revision` is the kit commit you noted in step 1.
- The JSON files `.claude/settings.json` and `.kiro/agents/factory.json` parse. The first has a non-empty deny list, the second a `deny` rule for `fs_write`: they are the fence that keeps Claude Code and Kiro out of the factory files. Check both whatever AGENTS is: they are factory files and stay in the project.
- `.github/copilot/settings.json` disables `lap`, `bmad-build` and `bmad-build-auto`. It stays in every project too. This limits Copilot's skill discovery, not its filesystem access; never report it as a Copilot fence or `doctor: OK` as proof that Copilot laps are supported.

Commit ("Install the factory from the kit at <commit>") and push: `git push -u origin main`.

## Step 4: Install and set up BMAD v7 (in PROJECT only)

Install into the required skill directories: use `-a claude-code` when AGENTS includes Claude Code **or Copilot**, and `-a kiro-cli` when it includes Kiro. Deduplicate these flags. Copilot discovers `.claude/skills/` directly; this destination does not require the Claude Code executable. For Copilot-only setup, use only `-a claude-code`, not an installer-specific Copilot destination.

```bash
npx -y skills add bmad-code-org/BMAD-METHOD/skills/core-tools --skill '*' -a claude-code -a kiro-cli -y --copy
npx -y skills add bmad-code-org/BMAD-METHOD/skills/method --skill '*' -a claude-code -a kiro-cli -y --copy
uv run --no-cache SKILLS/bmad/scripts/setup.py --project-root . --skill SKILLS/bmad --root SKILLS
```

`SKILLS` is `.claude/skills` when AGENTS includes `claude-code` or `copilot-cli`, else `.kiro/skills`.

Keep `--copy`: the installed skill folders must be real files, not symlinks into ignored `.agents/skills/`. The installer may also create an ignored `.agents/` directory; do not rely on or commit it.

The setup command prints JSON. It must show `"current": true` and an empty `"problems"` list (`"status"` may be `created` or `repaired`; both are fine). If it lists pending questions, ask the person; do not invent answers. Note the `version` it reports for your report.

**Check** that the factory's BMAD rules are picked up:

```bash
uv run --no-cache _bmad/scripts/resolve_customization.py --skill SKILLS/bmad-build --project-root . --key workflow
```

The output must contain the review lens id `factory-judge`, `"review": "thorough"`, and `MISSION.md` among `persistent_facts`. Also check that no folder under SKILLS is a symlink, and that `.claude/skills/lap/SKILL.md` and `.kiro/skills/lap/SKILL.md` still exist and are unchanged (`git status` shows them clean). When both destinations were selected, both hold the same BMAD skills; an unselected destination keeps only the kit's own skills.

With Copilot selected, run `copilot instruction list --json` and `copilot skill list --json` from PROJECT. Confirm the root `AGENTS.md` and the installed BMAD planning and `triage` skills are discovered. Discovery outside a trusted session may still list build skills as enabled: it does not prove that repository settings are active. Have the human trust the project in an interactive Copilot session and check `/skills`: `lap`, `bmad-build` and `bmad-build-auto` must be disabled there. If that interactive check is not done during setup, report it as an open Copilot setup step. If a trusted session enables a build skill, stop and report it; never change the settings to make it work.

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
- On a new project, both greens prove only that the workflows run, not that the judge catches anything: there is no backend to judge yet, and `harness/mutations/` holds no defects. Read the `calibrate` run's log: if it says `NOTICE: no defects in harness/mutations/ yet. Nothing was calibrated.`, report `calibrate` as "runs; nothing calibrated yet", never as "calibrated". The person calibrates after the first two or three tickets (`RUNBOOK.md`, "Calibrate the judge").

## Step 7: Branch protection (try, do not force)

Try to protect `main` in `OWNER/PROJECT` through the API (`gh api --hostname HOST -X PUT repos/OWNER/PROJECT/branches/main/protection --input <file>`; write the JSON body to a file, because piping it through a Windows shell can garble it): require a pull request; 0 required approvals; required status checks `gates`, `protected-paths` and `scope-guard`.

- If step 6 found that Actions cannot run, leave out the required status checks: until the factory judge runs, they would never report, so no pull request could merge except by an admin bypassing the rule. Report the checks as open, to be required once the person runs the judge.
- If GitHub refuses (a free plan answers 403 "Upgrade to GitHub Pro or make this repository public" for a private repository), do not work around it. Report it as open.

## Step 8: Record the setup, then report

First run `python KIT/bin/kit.py --kit KIT doctor` in PROJECT. It must still print `doctor: OK`. Each `open:` line it prints is a setup step still open (Actions off, a missing label, branch protection, no active BMAD initiative); every one goes into item 3 of the report, in its own words. "No active BMAD initiative" is always open after setup: the person sets it before planning (`RUNBOOK.md`, "Plan the product", step 0), because the fence keeps agents out of `_bmad/custom/`.

Then record the setup in the project. `PROJECT_NOTES.md` is the project's own file, not a factory file, and its "Setup status" section is for this. Replace that section's paragraph (keep the heading, leave the rest of the file alone) with:

- one line: the date, `Set up by an agent from factory-kit <commit>`, and the BMAD version;
- one line per step of `RUNBOOK.md`'s one-time setup, 1 to 6 (install the factory, BMAD, the settings, the labels, branch protection, what is still open): `done` or `open`, and for each open one, what the person does to finish it, in the words you use in item 3 below;
- the `calibrate` result from step 6 (for a new project: "runs; nothing calibrated yet");
- each `open:` line `doctor` printed just now, word for word.

Commit ("Record the setup status") and `git push`. If `main` refuses the push because step 7 protected it, push the commit to a branch `setup/status` instead, open a pull request for it with `gh`, and give its link in item 3; do not change the protection.

Give the person a short report:

1. The link to the repository, the local folder path, and the kit folder (KIT), which the project needs next to it for `kit.py sync`.
2. A table of steps 1–7: done, failed or open, one line each, with evidence (commit ids, workflow run links). For step 6, say what the greens prove: on a new project `calibrate` "runs; nothing calibrated yet".
3. What is left for them, with exact instructions:
   - Branch protection, if step 7 is open.
   - Without Actions: each lap runs the factory judge on its own pull request (lap step A10); require the three checks once the first lap has posted them (`RUNBOOK.md`, "Without GitHub Actions"). The judge needs Java 21 and Node 22 on the machine where laps run.
   - Set the active BMAD initiative, plan the product with BMAD (each planning step is its own `planning/<step>` pull request), and fill in `MISSION.md` themselves. Run laps with Claude Code or Kiro, never Copilot. If AGENTS is Copilot-only, explicitly report "planning and triage only; install Claude Code or Kiro before running laps". See `RUNBOOK.md`, "Plan the product" and "Copilot CLI: supervised planning and triage".
4. Anything that surprised you, or that this file or the kit's other documents got wrong, so the kit can be fixed.

Then tell the person to close this session. Start a fresh session inside the project for planning or triage. For a lap, use Claude Code or `kiro-cli chat --agent factory`, so the project's `AGENTS.md` and the agent's fence apply. Copilot's manual permissions require human supervision; do not recommend allow-all, assisted approvals or persistent blanket tool approvals.
