# One command to update a project from the kit, and one to port back

Date: 2026-11-22. Status: waiting for approval. Home: `factory-kit`.

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

## Intent

- **One command per direction.** `kit.py sync` updates a project from the kit. `kit.py port` carries a project's factory change back to the kit.
- **Whole files, never merges.** Every file in a project is one of: owned by the kit, owned by the project, generated, or merged line by line (below). Only the last kind is combined, and only by appending missing lines.
- **The project knows its kit revision,** so "what is new" is a `git log` between two commits.
- **Nothing gets past the judge.** The fence, the labels and the human merge stay exactly as they are.

## Design

### The kit's layout

```
factory-kit/
  template/            everything a project gets, at the path it gets it
    .claude/settings.json        the fenced version (today fence/claude-settings.json)
    .claude/skills/lap/  .kiro/  .github/  harness/  _bmad/custom/
    AGENTS.md  CLAUDE.md  FACTORY_RULES.md  RUNBOOK.md  MODIFYING.md  .gitattributes  skills-lock.json
    .gitignore                   lines to add to the project's .gitignore
    seed/                        project files, installed once, never again
      MISSION.md  README.md (today PROJECT_README.md)  PROJECT_NOTES.md  factory.json
  bin/kit.py           init, status, sync, port, doctor
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
| **Kit-owned** | everything under `template/` except `seed/` and `.gitignore` | Replaces the file when the kit changed it. Stops if the project changed it (see "Local changes") |
| **Project-owned** | `MISSION.md`, `README.md`, `PROJECT_NOTES.md`, `factory.json`, `docs/runtime/`, and every file not in `template/` | Never touches. `init` installs the `seed/` files once |
| **Generated** | `.github/CODEOWNERS` | Writes it from `template/.github/CODEOWNERS` and the owner in `factory.json` |
| **Merged lines** | `.gitignore` | Appends the template's lines that are missing. Never removes a line |

The list of project-owned files lives in `kit.py`, as `PERSONAL` does in ai-software-factory.

### No placeholders

- **The owner** is the only name a file needs. It goes in the project's `factory.json` (`{"owner": "sunilmunikar"}`) and into the generated `CODEOWNERS`.
- **`RUNBOOK.md` and `MODIFYING.md` use no names.** `gh api repos/{owner}/{repo}/...` fills in the current repository by itself, so does `gh browse`, and the dispatcher's worktree folder is written as "`<project>-wt/` next to this clone".
- **The host** already comes from `origin` in `serve.py`, `dispatch.py` and the lap skill (kit, 2026-11-20).
- **`README.md`** is a seed. `init` fills its names once, and from then on it is the project's.

### Project text out of kit files

- **`PROJECT_NOTES.md`** (seed, project-owned) holds what a project adds to the runbook: for the pilot, its intro, the "What stands in for what" table, the setup status and "What this pilot does not prove". `RUNBOOK.md` links to it in one line.
- **Projects keep no factory changelog.** A factory change found in a project is recorded in the kit's `CHANGELOG.md`, "(from `<project>`)", when it is ported. A project's existing `CHANGELOG.md` is project-owned: `sync` leaves it alone, and the project may keep it as history.

### The lock: `factory.lock.json`

`sync` writes it at the project root, the way `skills-lock.json` records BMAD (`.factory/` cannot be used: the judge ignores everything in it).

```json
{"kit": "https://github.com/sunilmunikar/factory-kit", "revision": "6dc58fa…",
 "files": {"harness/judge/judge.py": "sha256:…", "...": "..."}}
```

- **`revision`** is the kit commit last synced. `status` prints the kit commits since then, and `sync` puts them in the pull request body.
- **`files`** holds a hash of each kit-owned file as installed. Hashes are taken with line endings normalised to LF. The pilot's working tree is CRLF on Windows while the kit's is LF, so `.gitignore` looked different although its content was identical.

### Local changes: three-way, not two

For each kit-owned file, `sync` compares the project's copy (P), the lock's hash (L) and the kit's new version (K):

| Case | Meaning | `sync` |
|---|---|---|
| P = L, K = L | Nothing changed | Nothing |
| P = L, K ≠ L | The kit changed it | Replaces it |
| P ≠ L, K = P | The project made the change the kit now has (a port came back) | Updates the lock |
| P ≠ L, K ≠ P | The project changed it and the kit has something else | **Stops** and lists it: port it, or discard it with `--discard <file>` |

ai-software-factory compares P with K only, so it cannot tell "the kit changed it" from "the project changed it". It backs the file up to `.factory/backup/` and replaces it. Here a project's change is never replaced without anyone noticing: the `MODIFYING.md` rule "fix it in the project, re-run the lap, carry it to the kit" depends on it.

### The commands

All run from the project's root, with the kit as a local clone (a sibling folder, or `--kit <path>`):

```
python ../factory-kit/bin/kit.py init            # new project: seeds, kit files, lock (replaces init-project.sh)
python ../factory-kit/bin/kit.py status          # project revision vs kit main, new kit commits, locally changed files
python ../factory-kit/bin/kit.py sync            # kit -> project, on a new branch factory/kit-<short revision>
python ../factory-kit/bin/kit.py port <name>     # project -> kit: changed kit-owned files onto port/<name> in the kit
python ../factory-kit/bin/kit.py doctor          # the fence, CODEOWNERS, FACTORY_RULES.md section 2 and guards.json name the same paths; the lap skills are identical
```

**`sync`:**
1. Refuses a dirty project tree, or a kit clone with uncommitted changes or behind its `origin/main`.
2. Creates `factory/kit-<rev>` from `origin/main`.
3. Applies the table above and writes the lock.
4. Runs `doctor`.
5. Writes the pull request body (new kit commits, files changed, files stopped) to a file and prints its path.

It does not commit, push or open the pull request.

**`port`:**
1. Takes the kit-owned files where P ≠ L.
2. Creates `port/<name>` in the kit from `origin/main` and copies them in, and only them.
3. Refuses a file whose kit version also moved since the lock's revision, and shows both versions.

It touches only the kit clone, where the fence is off.

**`status`, `port` and `doctor` write nothing in the project,** so a lap agent may run them. `sync` and `init` write fenced paths, so **a human runs them**: one command, where today it was 38 copied files. The agent then checks the result, runs the tests, commits, pushes and opens the pull request. The human adds `human-judge-change` and merges, as today.

### What changes in the documents

- **`MODIFYING.md`:** the two git recipes become `kit.py port` and `kit.py sync`. "Changes that need extra care" stays, and `doctor` checks the five-place list.
- **`AGENT_SETUP.md` and the RUNBOOK's one-time setup:** "create from the template, run `init-project.sh`" becomes "create an empty repository, clone the kit next to it, run `kit.py init`". This also removes the GitHub Enterprise problem, where the template repository did not exist on the host (2026-11-20).

## Migration

**Kit, one pull request:**
1. `git mv` the factory files into `template/`. Move `fence/*` to their places in `template/`, `PROJECT_README.md` to `template/seed/README.md`, and `MISSION.md` to `template/seed/`.
2. Take the placeholders out of `RUNBOOK.md` and `MODIFYING.md` (`{owner}/{repo}` for `gh`).
3. Add `bin/kit.py`, `bin/test_kit.py`, `.github/workflows/kit.yml`, the kit's root `CLAUDE.md` and settings.
4. Delete `init-project.sh` and `fence/`. Untick "Template repository".

**Pilot, one pull request**, the acceptance test:
1. Add `factory.json` and `PROJECT_NOTES.md`, the latter with the pilot's sections from `RUNBOOK.md`.
2. A human runs `kit.py sync --adopt` (the first sync has no lock). It must:
   - change only `RUNBOOK.md`, back to the kit's text;
   - leave the fence files and `MISSION.md` untouched;
   - regenerate an identical `CODEOWNERS`;
   - write the lock.
3. Then a second `kit.py sync` must report "nothing to do".

`--adopt` takes a file as installed when it equals the kit's version, and lists every other one for the human. For the pilot that list is the five files above.

## Tests (`bin/test_kit.py`)

Each test runs against scratch Git repositories:

- `init` on an empty repository gives a project that `doctor` passes;
- each row of the three-way table;
- project-owned files and seeds are never written after `init`;
- `.gitignore` lines are appended once, never removed;
- `CODEOWNERS` is regenerated from `factory.json`;
- CRLF and LF copies hash the same;
- `port` copies only changed kit-owned files and refuses when the kit moved too;
- `sync` refuses a dirty tree or a stale kit clone;
- a no-op `sync` changes nothing.

They must pass on Windows (Git Bash) and Linux, given factory-kit#12.

## Not in scope

- **Pinning BMAD.** It stays in `skills-lock.json`, which becomes a kit-owned file. An upgrade is tried in one project, then ported.
- **Changing the judge, the fence's rules, the labels, or who merges.**
- **Several kits, or a project choosing parts of the kit.**

## Open questions

1. **Local change and new kit version (the last row):** stop, as proposed, or back the file up and replace it, as ai-software-factory does? Stopping is safer; backing up never blocks an update.
2. **`CODEOWNERS`:** generated, as proposed, or a seed the project keeps up by hand? Generating keeps it in step when the protected list grows, as it did for Kiro.
3. **Generate the fence files from `guards.json`,** instead of only checking them with `doctor`? One list would then drive four files, but a project could no longer add its own deny rules to `.claude/settings.json`.
4. **The pilot's existing `CHANGELOG.md`:** keep it as history, or move its entries into the kit's changelog and delete it?
