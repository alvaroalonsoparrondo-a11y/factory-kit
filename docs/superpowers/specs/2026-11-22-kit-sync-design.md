# One command to update a project from the kit

Date: 2026-11-22. Status: decisions taken (see "Decisions"), waiting for approval to build. Home: `factory-kit`.

Inspired by [coleam00/ai-software-factory](https://github.com/coleam00/ai-software-factory): its factory repository keeps a `template/` folder, and one command (`bin/factory.py init`) both installs and upgrades a project.

## Why

On 2026-11-21 and 22, `factory-pilot` was brought up to kit `main`. It took two pull requests (factory-pilot#13, #14) and most of a session. Every step of the recipe in `MODIFYING.md` worked against us:

| What happened | Why |
|---|---|
| 10 of 11 kit commits conflicted on a trial cherry-pick | A project's factory files are edited copies: `CHANGELOG.md`, `RUNBOOK.md`, the lap skill, the fence paths |
| Kit-only files had to be left out by hand | `README.md`, `PROJECT_README.md`, `init-project.sh`, `AGENT_SETUP.md`, `fence/` and `docs/` sit beside the factory files, at the same level |
| The fence had to be moved by hand | It lives in `fence/` in the kit and at `.claude/settings.json` and `.kiro/agents/factory.json` in a project |
| Real names had to be put back | `__OWNER__`, `__PROJECT__`, `__HOST__` and `__PARENT_DIR__` are filled in place, inside files the kit also changes |
| `RUNBOOK.md` was merged by hand | It holds kit text and project text (the pilot's intro, its stand-in table, its closing sections) |
| Finding the last sync meant reading both changelogs | Nothing records which kit revision a project has |
| 38 fenced files were staged in a temp folder for a human to copy | The agent may not write fenced paths, and there was no one command for the human to run |
| The second update (#14) needed a conflict check first | Its `CHANGELOG.md` hunk could not apply, because the two changelogs differ |

After both updates, the pilot differs from kit `main` in five files only, and each difference has a reason:

| File | Why it differs |
|---|---|
| `.claude/settings.json`, `.kiro/agents/factory.json` | The fence: on in projects, off in the kit |
| `.github/CODEOWNERS` | The owner's name |
| `MISSION.md` | The project's own mission |
| `RUNBOOK.md` | Real names in place of placeholders, plus pilot-only sections |

The design below gives each of these a home, so that an update copies whole files and never merges.

## How changes reach the kit

There are two phases, and the design is built for the second.

- **Now, while the kit is young: a change may start in a project.** A lap shows a problem, the fix is made in the project so the lap can be run again, and it is carried to the kit. This is only to improve the kit faster. `sync` lets the newer version win (see "Local changes"), so a fix made in the project is not lost before it reaches the kit.
- **Once the kit is mature: every change is a request for change, done in the kit.**
  1. A project finds a problem.
  2. Someone opens a GitHub issue in `factory-kit` saying what was seen, where, and in which lap, as factory-kit#12 and #14 to #16 did.
  3. The change is built and tested in the kit, on a `factory/<name>` branch, and a human merges it.
  4. Projects take it with `kit.py sync`.

  Projects then do not change kit-owned files at all, and `sync` only ever moves one way.

Because the second phase is the lasting one, carrying a change from a project to the kit gets no command of its own: in the first phase it is a small manual copy (see "Carrying a change to the kit, for now").

## Intent

- **One command to update a project:** `kit.py sync`.
- **Whole files, almost never merges.** Every file in a project is one of four kinds (below). Only the fence files are combined, and only their deny lists.
- **The project knows its kit revision,** so "what is new" is a `git log` between two commits.
- **The factory's history lives in the kit only.** Projects keep no factory changelog.
- **Nothing gets past the judge.** The fence, the labels and the human merge stay exactly as they are.

## Design

### The kit's layout

```
factory-kit/
  template/            everything a project gets, at the path it gets it
    .claude/settings.json        the fenced version (today fence/claude-settings.json)
    .kiro/agents/factory.json    the fenced version (today fence/kiro-factory.json)
    .claude/skills/lap/  .kiro/skills/lap/  .github/  harness/  _bmad/custom/
    AGENTS.md  CLAUDE.md  FACTORY_RULES.md  RUNBOOK.md  MODIFYING.md  .gitattributes  skills-lock.json
    .gitignore                   lines to add to the project's .gitignore
    seed/                        project files, installed once by init, never again
      MISSION.md  README.md (today PROJECT_README.md)  PROJECT_NOTES.md  .github/CODEOWNERS
  bin/kit.py           init, status, sync, doctor
  bin/test_kit.py
  .github/workflows/kit.yml      the kit's own CI: kit.py tests, then the harness tests in template/
  .claude/settings.json          the kit's own settings: no fence, force push denied
  CLAUDE.md                      instructions for agents changing the kit
  README.md  CHANGELOG.md  AGENT_SETUP.md  docs/
```

What goes away: `fence/`, `init-project.sh`, the placeholders, and the kit being a GitHub template repository. The guards' `skip_template` flag is no longer needed: `template/.github/` is not read by GitHub, so the kit's own pull requests are judged only by `kit.yml`.

### The four kinds of file in a project

| Kind | Files | What `sync` does |
|---|---|---|
| **Kit-owned** | everything under `template/` except `seed/`, `.gitignore` and the two fence files | Replaces the file when the kit changed it. If the project changed it too, the newer change wins (see "Local changes") |
| **Project-owned** | `MISSION.md`, `README.md`, `PROJECT_NOTES.md`, `.github/CODEOWNERS`, `docs/runtime/`, and every file not in `template/` | Never touches. `init` installs the `seed/` files once |
| **Fence** | `.claude/settings.json`, `.kiro/agents/factory.json` | Merges the deny lists: the kit's entries are added or removed, the project's own entries and every other setting stay |
| **Merged lines** | `.gitignore` | Appends the template's lines that are missing. Never removes a line |

The list of project-owned files lives in `kit.py`, as `PERSONAL` does in ai-software-factory.

### The fence: the project may add to it

A project may deny more than the kit does, for example a path of its own product. So the fence files are not replaced whole:

- **What the kit manages.** The lock records which deny entries came from the kit. On `sync`:
  - a kit entry the project lacks is added;
  - an entry the kit dropped since the last sync is removed;
  - every other entry is the project's own, and stays.
- **What `sync` leaves alone.** Everything else in the two files stays as the project has it: Claude Code's other settings, Kiro's other tools. That includes the order of the deny list, with new entries appended.
- **What `doctor` checks.** Every path in `guards.json`'s `protected-paths` is still denied, in both files. A project may add rules but not lose the kit's.

### `CODEOWNERS`: written by hand

`CODEOWNERS` is a seed. `init` writes it once, with the owner the human gives (`kit.py init --owner <user or team>`). After that the project keeps it. When the kit's protected list grows, as it did for Kiro, `doctor` lists each protected path that `CODEOWNERS` does not cover. It warns only: a missing line does not weaken the judge, because `protected-paths` and its label decide.

### No placeholders

- **`RUNBOOK.md` and `MODIFYING.md` use no names.** `gh api repos/{owner}/{repo}/...` fills in the current repository by itself, so does `gh browse`, and the dispatcher's worktree folder is written as "`<project>-wt/` next to this clone".
- **The host** already comes from `origin` in `serve.py`, `dispatch.py` and the lap skill (kit, 2026-11-20).
- **The seeds** (`README.md`, `CODEOWNERS`) get their names from `init`, once. From then on they are the project's.

### Project text out of kit files

- **`PROJECT_NOTES.md`** (seed, project-owned) holds what a project adds to the runbook: for the pilot, its intro, the "What stands in for what" table, the setup status and "What this pilot does not prove". `RUNBOOK.md` links to it in one line.
- **Projects keep no factory changelog.** What a project found is recorded where it is acted on:
  - in a mature kit, in the issue;
  - in the kit's `CHANGELOG.md`, "(from `<project>`)", when the change lands.

  A project's pull request that takes a `sync` lists the kit commits it brings. That is the project's record.

### The lock: `factory.lock.json`

`sync` writes it at the project root, the way `skills-lock.json` records BMAD (`.factory/` cannot be used: the judge ignores everything in it).

```json
{"kit": "https://github.com/sunilmunikar/factory-kit", "revision": "6dc58fa…",
 "files": {"harness/judge/judge.py": "sha256:…", "...": "..."},
 "fence": {".claude/settings.json": ["Edit(/harness/**)", "..."], ".kiro/agents/factory.json": ["..."]}}
```

- **`revision`** is the kit commit last synced. `status` prints the kit commits since then, and `sync` puts them in the pull request body.
- **`files`** holds a hash of each kit-owned file as installed. Hashes are taken with line endings normalised to LF. The pilot's working tree is CRLF on Windows while the kit's is LF, so `.gitignore` looked different although its content was identical.
- **`fence`** holds the deny entries the kit manages, so a project's own entries can be told apart.

### Local changes: the newer change wins

For each kit-owned file, `sync` compares the project's copy (P), the lock's hash (L) and the kit's new version (K):

| Case | Meaning | `sync` |
|---|---|---|
| P = L, K = L | Nothing changed | Nothing |
| P = L, K ≠ L | The kit changed it | Replaces it |
| P ≠ L, K = P | The project made the change the kit now has (it was carried over) | Updates the lock |
| P ≠ L, K = L | Only the project changed it | Keeps it, and lists it as "not in the kit yet" |
| P ≠ L, K ≠ L, K ≠ P | Both changed it | **The newer one wins** |

- **Who is newer** is decided by commit time: the project's last commit to the file, against the kit's last commit to it after the lock's revision. `sync` refuses a dirty tree, so the project's change is always a commit.
- **Nothing is lost.** The version that lost stays in Git history, and `sync` names every such file, which version won, and the commit of the version that lost. If the project's version wins, it is also listed as "not in the kit yet".
- **Compared with ai-software-factory:** it compares P with K only, so it cannot tell "the kit changed it" from "the project changed it". It backs the file up and always lets the kit win. The lock makes the comparison three-way here, and lets the newer change win.

### The commands

All run from the project's root, with the kit as a local clone (a sibling folder, or `--kit <path>`):

```
python ../factory-kit/bin/kit.py init --owner <user>   # new project: seeds, kit files, fence, lock (replaces init-project.sh)
python ../factory-kit/bin/kit.py status                # project revision vs kit main, new kit commits, files "not in the kit yet"
python ../factory-kit/bin/kit.py sync                  # kit -> project, on a new branch factory/kit-<short revision>
python ../factory-kit/bin/kit.py doctor                # fence covers guards.json; lap skills identical; CODEOWNERS covers the protected paths (warning)
```

**`sync`:**
1. Refuses a dirty project tree, or a kit clone with uncommitted changes or behind its `origin/main`.
2. Creates `factory/kit-<rev>` from `origin/main`.
3. Applies the tables above and writes the lock.
4. Runs `doctor`.
5. Writes the pull request body (new kit commits, files changed, files where the project won, files not in the kit yet) to a file and prints its path.

It does not commit, push or open the pull request.

**Who runs what.** `status` and `doctor` write nothing, so a lap agent may run them. `init` and `sync` write fenced paths, so **a human runs them**: one command, where today it was 38 copied files. The agent then checks the result, runs the tests, commits, pushes and opens the pull request. The human adds `human-judge-change` and merges, as today.

### Carrying a change to the kit, for now

While the kit is young, a fix made in a project reaches the kit by hand. This needs no recipe, because paths are the same on both sides and no kit-owned file holds a name:

1. `kit.py status` lists the files "not in the kit yet".
2. Copy them into `template/` on a `factory/<name>` branch in the kit.
3. Add the `CHANGELOG.md` entry and open the pull request.

The next `sync` sees P = K and only updates the lock. There is no `port` command: once the kit is mature, changes start as issues in the kit, and a command for the other direction would only be dead weight.

### What changes in the documents

- **`MODIFYING.md`:**
  - The kit-to-project recipe becomes `kit.py sync`.
  - The project-to-kit recipe becomes the three steps above, marked as the young-kit phase.
  - A new first rule: a change is requested as an issue in `factory-kit`.
  - "Changes that need extra care" stays, and `doctor` checks the fence part of the five-place list.
- **`AGENT_SETUP.md` and the RUNBOOK's one-time setup:** "create from the template, run `init-project.sh`" becomes "create an empty repository, clone the kit next to it, run `kit.py init --owner <user>`". This also removes the GitHub Enterprise problem, where the template repository did not exist on the host (2026-11-20).

## Migration

**Kit, one pull request:**
1. `git mv` the factory files into `template/`. Move `fence/*` to their places in `template/`, `PROJECT_README.md` to `template/seed/README.md`, and `MISSION.md` and `.github/CODEOWNERS` to `template/seed/`.
2. Take the placeholders out of `RUNBOOK.md` and `MODIFYING.md` (`{owner}/{repo}` for `gh`).
3. Add `bin/kit.py`, `bin/test_kit.py`, `.github/workflows/kit.yml`, the kit's root `CLAUDE.md` and settings.
4. Delete `init-project.sh` and `fence/`. Untick "Template repository".

**Pilot, one pull request**, the acceptance test:
1. Add `PROJECT_NOTES.md` with the pilot's sections from `RUNBOOK.md`.
2. Delete the pilot's `CHANGELOG.md`. Its factory findings are already in the kit's changelog, "(from `factory-pilot`)", and its history stays in Git.
3. A human runs `kit.py sync --adopt` (the first sync has no lock). It must:
   - change only `RUNBOOK.md`, back to the kit's text;
   - leave the fence files as they are (they already hold every kit entry), `CODEOWNERS` and `MISSION.md` untouched;
   - write the lock.
4. Then a second `kit.py sync` must report "nothing to do".

`--adopt` takes a file as installed when it equals the kit's version, and lists every other one for the human. For the pilot that list is `RUNBOOK.md` only: the other four of the five files are now project-owned or fence.

## Tests (`bin/test_kit.py`)

Each test runs against scratch Git repositories:

- `init` on an empty repository gives a project that `doctor` passes;
- each row of the local-changes table, including both outcomes of the newer-wins row;
- fence merge: kit entries added and removed, project entries and other settings kept, `doctor` fails when a protected path is no longer denied;
- project-owned files and seeds are never written after `init`;
- `.gitignore` lines are appended once, never removed;
- CRLF and LF copies hash the same;
- `sync` refuses a dirty tree or a stale kit clone;
- a no-op `sync` changes nothing.

They must pass on Windows (Git Bash) and Linux, given factory-kit#12.

## Not in scope

- **Pinning BMAD.** It stays in `skills-lock.json`, which becomes a kit-owned file. An upgrade is tried in one project, then made in the kit.
- **Changing the judge, the fence's rules, the labels, or who merges.**
- **Several kits, or a project choosing parts of the kit.**

## Decisions

Taken 2026-11-22 by the kit's owner:

1. **A file both sides changed: the latest change wins.** Decided by commit time; the version that lost stays in Git history and is named in the pull request.
2. **`CODEOWNERS` is written by hand.** `init` seeds it once; `doctor` warns when it misses a protected path.
3. **A project may change the deny list.** `sync` merges the kit's entries into the fence files and keeps the project's own; `doctor` checks that the kit's protected paths stay denied.
4. **The changelog lives in the kit only.** Projects keep none; the pilot's is deleted in the migration.

Also decided: carrying a change from a project to the kit exists only to improve the kit faster while it is young. A mature kit takes every change as a request for change (a GitHub issue in `factory-kit`), built and tested in the kit. That is why there is no `port` command.
