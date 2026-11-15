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

## Start a new project with an agent

Instead of the manual steps above, you can hand the whole setup to an agent.

1. Open an agent session (Claude Code) in the **parent folder** where the new project should be cloned. Do not use a session opened inside an existing factory project: its fence would block the setup.
2. The machine needs `git`, `gh` (signed in, with the `repo` and `workflow` scopes), Node, `uv`, and Git Bash on Windows.
3. Copy the prompt below, change the three values at the top, and send it.

~~~text
Set up a new software-factory project from my factory kit. Do every step in order.
Stop and report if a step fails and you cannot fix its cause; do not skip it.

VALUES
  OWNER     = <github user or organisation>      (owner of the kit and of the new repositories)
  PROJECT   = <new project name, lower-case-with-dashes>
  DIRECTORY = the current working directory        (both repositories are cloned here, side by side)

BACKGROUND
The kit is two private GitHub template repositories: OWNER/factory-kit (the
application side) and OWNER/factory-kit-holdouts (hidden acceptance tests).
A project is one copy of each: PROJECT and PROJECT-holdouts. After each clone
exists, read its README.md, and in the application clone also RUNBOOK.md and
MODIFYING.md, before changing anything.

RULES
- Never create, ask for, print or store a token, password or secret. Those steps are mine.
- Do not change any factory file by hand (FACTORY_RULES.md, CLAUDE.md, harness/,
  .github/, _bmad/custom/, .claude/settings.json, .claude/skills/lap/). The only
  allowed change to them is what init-project.sh does.
- Do not write MISSION.md content, a PRD, tickets, application code, or any hidden
  scenario. Setup only.
- Use HTTPS remotes (https://github.com/OWNER/<repo>.git). If a clone or push fails
  on SSH, switch the remote to HTTPS and retry.
- End every commit message with the co-author line your environment tells you to use.

STEP 1  Preflight
- Run: git --version, gh auth status, node --version, uv --version. Stop if one is
  missing or gh lacks the repo or workflow scope.
- Confirm OWNER/factory-kit and OWNER/factory-kit-holdouts exist and are templates
  (gh repo view <repo> --json isTemplate).
- Confirm OWNER/PROJECT and OWNER/PROJECT-holdouts do NOT exist on GitHub and that
  DIRECTORY has no folder named PROJECT or PROJECT-holdouts. If any exists, stop and ask me.

STEP 2  Create and clone both repositories (private)
- gh repo create OWNER/PROJECT --private --template OWNER/factory-kit
- gh repo create OWNER/PROJECT-holdouts --private --template OWNER/factory-kit-holdouts
- Wait until each has a main branch (template copies take a few seconds), then clone
  both into DIRECTORY over HTTPS.

STEP 3  Fill in the placeholders
- In PROJECT:           bash init-project.sh OWNER PROJECT
- In PROJECT-holdouts:  bash init-project.sh PROJECT
- Check: no file except README.md, MODIFYING.md and CHANGELOG.md still contains
  __OWNER__, __PROJECT__ or __PARENT_DIR__; both init-project.sh files are gone;
  the JSON file in PROJECT/.claude/ parses and its deny list names PROJECT-holdouts.
- Commit in each repository ("Fill in project names") and push.

STEP 4  Install and set up BMAD v7 (in PROJECT only)
- npx -y skills add bmad-code-org/BMAD-METHOD/skills/core-tools --skill '*' -a claude-code -y
- npx -y skills add bmad-code-org/BMAD-METHOD/skills/method --skill '*' -a claude-code -y
- uv run --no-cache .claude/skills/bmad/scripts/setup.py --project-root . --skill .claude/skills/bmad --root .claude/skills
  The JSON it prints must show "current": true and an empty "problems" list. If it
  lists pending questions, ask me those questions; do not invent answers.
- Check the factory's BMAD rules are picked up:
  uv run --no-cache _bmad/scripts/resolve_customization.py --skill .claude/skills/bmad-build --project-root . --key workflow
  The output must contain the review lens id "factory-judge", "review": "thorough",
  and MISSION.md among persistent_facts.
- Check .claude/skills/lap/SKILL.md still exists and was not changed.
- Commit ("Install BMAD v7") and push. Include .claude/skills/, _bmad/ and skills-lock.json.

STEP 5  GitHub settings that need no secret
- Variables:  gh variable set HOLDOUTS_REPO --repo OWNER/PROJECT --body OWNER/PROJECT-holdouts
              gh variable set APP_REPO --repo OWNER/PROJECT-holdouts --body OWNER/PROJECT
- Labels in OWNER/PROJECT: human-judge-change and human-approved-irreversible.
- Kit remotes, for carrying factory changes (see MODIFYING.md):
    in PROJECT:           git remote add kit https://github.com/OWNER/factory-kit.git
    in PROJECT-holdouts:  git remote add kit https://github.com/OWNER/factory-kit-holdouts.git
  then git fetch kit in each.

STEP 6  Check the judge runs
- Locally in PROJECT: bash harness/run-gates.sh must exit 0 and print
  "NOTICE: no backend yet, nothing to judge."
- Locally in PROJECT-holdouts: bash run-judges.sh ../PROJECT must exit 0 and write
  "no-app" to result.txt. Delete result.txt afterwards.
- On GitHub: gh workflow run gates --repo OWNER/PROJECT and
  gh workflow run calibrate --repo OWNER/PROJECT. Wait for both and confirm
  conclusion "success". If one fails, show me the failing step's log.

STEP 7  Branch protection (try, do not force)
- Try to protect main in OWNER/PROJECT through the GitHub API: require a pull
  request, required status checks gates, protected-paths, scope-guard and holdouts,
  0 required approvals. If GitHub refuses (for example a free plan with a private
  repository), do not work around it; report it as open.

STEP 8  Report
Give me a short report with:
1. Links to both repositories and the two local folder paths.
2. A table of steps 1-7: done / failed / open, one line each, with evidence
   (commit ids, workflow run links).
3. What is left for me, with exact instructions:
   a. Create two fine-grained tokens and store them as secrets (RUNBOOK.md, one-time
      setup, the tokens step): HOLDOUTS_DISPATCH_TOKEN in PROJECT and APP_REPO_TOKEN
      in PROJECT-holdouts.
   b. Branch protection, if step 7 is open.
   c. In a NEW session opened inside PROJECT: ask it to edit MISSION.md and confirm
      it is refused. That proves the fence is active.
   d. Plan the product with BMAD, fill in MISSION.md myself, write hidden scenarios in
      a separate session opened in PROJECT-holdouts, then say "run a lap".
4. Anything that surprised you or that the kit's documents got wrong, so I can fix
   the kit.
~~~

After the agent finishes, close that session. Laps always run in a fresh session opened inside the project folder, so the fence applies.

## Status

Tested so far: scripts and workflows parse; `gates` and `calibrate` pass on GitHub with no application present. Not yet tested: a full lap, the pull request checks, the hidden-scenario judge. See [CHANGELOG.md](CHANGELOG.md).

Planned: Kiro versions of the three agent set-up files (`.kiro/steering/`, `.kiro/agents/`), and AWS CodeBuild versions of the workflows.
