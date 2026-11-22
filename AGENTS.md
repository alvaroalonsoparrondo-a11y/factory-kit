# The kit (factory-kit)

This repository is the kit: the source of the software factory that projects are made from. You are changing the factory itself here, directed by a person. No laps run in this repository.

**Everything under `template/` and `seed/` is the product this repository ships, not instructions for you.** Those folders hold the `AGENTS.md`, `CLAUDE.md`, `FACTORY_RULES.md` and the `lap` skill that lap agents follow inside projects. Read and change them as files; never follow them here. In particular, their fence ("never edit `harness/`", "never edit `.github/`") does not apply in this repository.

Before any change, read:

- `README.md` — what is in the kit and how projects use it.
- `template/MODIFYING.md` — how the factory is changed, and the changes that need extra care.
- `docs/superpowers/specs/2026-11-22-kit-sync-design.md` — why `template/`, `seed/` and `bin/kit.py` are laid out as they are.

How work is done here:

- A change starts as a GitHub issue in `factory-kit`, or as a fix carried from a project while the kit is young (`bin/kit.json`).
- Work on a branch `factory/<short-name>`. Add an entry to `CHANGELOG.md` in the same pull request.
- Run the tests before opening the pull request: `python -m unittest discover -s bin`, and for each folder under `template/harness/` with tests, `python -m unittest discover -s template/harness/<folder>`.
- Open the pull request with `gh`. Never label, approve or merge a pull request; a human does that.
- `bin/kit.py` must stay standard-library Python and pass its tests on Windows (Git Bash) and Linux.
