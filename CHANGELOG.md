# Changelog

Newest first. One entry per factory change: what was seen, where, and what changed. See [MODIFYING.md](MODIFYING.md).

## 2026-11-15 — First end-to-end setup test (`factory-trial`)

`AGENT_SETUP.md` was followed step by step to create a throwaway project. Steps 1–6 passed as written; step 7 was refused by GitHub (free plan, private repository), as the instructions expect.

Also checked on a trial pull request there: `protected-paths` and `scope-guard` went red on a change to `harness/` and a `security/` path, and green after the two approval labels were added; `gates` passed; pushes to `main` started `gates` normally.

Changes from the test:
- **Clear error when the dispatch secret is missing.** The holdouts request failed with a generic `gh` message; it now names the secret and variable to set.
- **A project gets its own README.** A new project kept the kit's README ("this repository is a template"). `init-project.sh` now swaps in `PROJECT_README.md` and removes the kit-only `AGENT_SETUP.md` and `CHANGELOG.md`.
- **`AGENT_SETUP.md` wording:** setup status `repaired` is fine; the exact refusal text for branch protection; push-triggered `gates` runs are expected.

Still untested: the hidden-scenario judge with real tokens, and a full lap. The missing push-triggered runs seen in `factory-pilot` did not happen in `factory-trial`; that looks specific to the pilot repository.

## 2026-11-15 — Agent setup prompt

- **`AGENT_SETUP.md` added; README prompt shortened.** The first version put all eight setup steps inside a prompt in the README. That duplicated `RUNBOOK.md` and would drift, so the steps moved to `AGENT_SETUP.md` and the prompt now only gives owner, project, folder and two guard rules, and points to that file. Pattern taken from the short install prompt of coleam00/ai-software-factory. Not yet run end to end.

## 2026-11-15 — First version

Made from the `factory-pilot` project before it had any product code.

- **Kit split from the project.** BMAD's own skills are no longer committed; each project installs them. Project names became placeholders, filled in by `init-project.sh`.
- **Maven cache removed from the workflows.** Seen in `factory-pilot`: the Java set-up step failed because no `pom.xml` exists before the walking skeleton.
- **Manual trigger added to `gates`.** Seen in `factory-pilot`: pushes to `main` did not start the workflow, so it could not be checked without one. Cause not found yet.
- **Action versions raised** to the current major versions, after deprecation warnings.
- **No separate reviewer agent.** BMAD v7's build already reviews with fresh subagents, so the factory adds one review lens ("Factory Judge") in `_bmad/custom/bmad-build.toml`.

### Known gaps

- No full lap has run yet. The pull request checks and the hidden-scenario judge are untested.
- Pushes to `main` did not start `gates` in `factory-pilot`; unexplained.
- The fence is a guard rail: a shell command can still reach a denied path.
- Claude Code and GitHub Actions only. Kiro and CodeBuild versions are planned.
