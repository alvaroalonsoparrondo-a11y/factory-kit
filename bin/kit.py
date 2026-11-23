#!/usr/bin/env python3
"""The kit's tool: install the factory in a project, and keep it up to date. Human-owned.

Standard library only (Python 3.11+). Run it from the project's root, with a clone of
`factory-kit` next to the project (or name it with --kit):

  python ../factory-kit/bin/kit.py init --owner <user or team> [--project NAME] [--host HOST]
  python ../factory-kit/bin/kit.py status
  python ../factory-kit/bin/kit.py sync [--adopt <kit revision>] [--discard <file> ...]
  python ../factory-kit/bin/kit.py doctor [--offline]

`init` and `sync` write fenced files, so a human runs them. `status` and `doctor` write nothing.
`doctor` also lists what is still open in the project's setup (GitHub Actions, the labels, branch
protection, BMAD, the active initiative); `--offline` leaves out the questions to GitHub.
The design is docs/superpowers/specs/2026-11-22-kit-sync-design.md in factory-kit.

Every file in a project is one of four kinds, by where it lives in the kit:
- the kit's (`template/`): replaced when the kit changed it; the change that reached `main` later
  wins when the project changed it too;
- the project's (`seed/`, plus PROJECT_FILES): `init` copies the seeds once, nothing touches them after;
- the fence (FENCE): the kit's deny entries are merged in, the project's own entries stay;
- merged lines (`template/.gitignore`): missing lines are appended.

`kit.lock.json` in the project records the kit revision, a hash of each of the kit's files as the
kit has them (line endings normalised), and the kit's fence entries.
"""
import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
LOCK = "kit.lock.json"
TEMPLATE, SEED = "template", "seed"
GITIGNORE = ".gitignore"
CLAUDE_FENCE, KIRO_FENCE = ".claude/settings.json", ".kiro/agents/factory.json"
FENCE = (CLAUDE_FENCE, KIRO_FENCE)
# Where a fence file lived before template/ existed (2026-11-21 to the migration).
OLD_FENCE = {CLAUDE_FENCE: "fence/claude-settings.json", KIRO_FENCE: "fence/kiro-factory.json"}
# The project's own files that are not seeds.
PROJECT_FILES = ("skills-lock.json",)
PROJECT_DIRS = ("docs/runtime/", "docs/triage/")
# Skills both agents run: the Kiro copy must equal the Claude one.
SKILL_PAIRS = tuple((f".claude/skills/{n}/SKILL.md", f".kiro/skills/{n}/SKILL.md") for n in ("lap", "triage"))
GUARDS = "harness/judge/guards.json"
CODEOWNERS = ".github/CODEOWNERS"
PLACEHOLDERS = ("__OWNER__", "__PROJECT__", "__HOST__")
# What the one-time setup in RUNBOOK.md leaves in place; `doctor` lists what is still open.
LABELS = ("human-judge-change", "human-approved-irreversible", "human-granted-round")
REQUIRED_CHECKS = ("gates", "protected-paths", "scope-guard")
SKILL_DIRS = (".claude/skills", ".kiro/skills")
BMAD_USER_CONFIG = "_bmad/custom/config.user.toml"


class Stop(Exception):
    """A refusal or a stop, with the message for the human."""


# ---------------------------------------------------------------- git and files

def git(cwd, *args, check=True):
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)
    if check and done.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed in {cwd}:\n{done.stderr.decode(errors='replace').strip()}")
    return done


def out(cwd, *args, check=True):
    return git(cwd, *args, check=check).stdout.decode("utf-8", errors="replace").strip()


def show(cwd, rev, path):
    """A file's bytes at a revision, or None if it is not there."""
    done = git(cwd, "show", f"{rev}:{path}", check=False)
    return done.stdout if done.returncode == 0 else None


def normal(data):
    """Text with LF line endings, so a CRLF working tree hashes as its LF commit does."""
    return data if data is None or b"\0" in data else data.replace(b"\r\n", b"\n")


def digest(data):
    return None if data is None else "sha256:" + hashlib.sha256(normal(data)).hexdigest()


def read(root, rel):
    p = Path(root) / rel
    return p.read_bytes() if p.is_file() else None


def write(root, rel, data):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


# ---------------------------------------------------------------- the kit

class Kit:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not (self.path / TEMPLATE).is_dir() or not (self.path / "bin" / "kit.py").is_file():
            raise Stop(f"{self.path} is not a clone of factory-kit (no template/ or bin/kit.py)")
        self.rev = out(self.path, "rev-parse", "HEAD")

    def check_clean(self):
        if out(self.path, "status", "--porcelain"):
            raise Stop(f"The kit clone {self.path} has uncommitted changes. Commit or remove them first.")
        if git(self.path, "rev-parse", "--verify", "-q", "origin/main", check=False).returncode == 0:
            git(self.path, "fetch", "-q", "origin", check=False)
            behind = out(self.path, "rev-list", "--count", "HEAD..origin/main")
            if behind != "0":
                raise Stop(f"The kit clone is {behind} commit(s) behind origin/main. Run `git pull` in {self.path}.")

    @property
    def url(self):
        return out(self.path, "remote", "get-url", "origin", check=False) or str(self.path)

    @property
    def phase(self):
        data = show(self.path, "HEAD", "bin/kit.json")
        return json.loads(data)["phase"] if data else "young"

    def tracked(self, folder):
        names = out(self.path, "ls-tree", "-r", "--name-only", "HEAD", "--", folder + "/")
        return [n[len(folder) + 1:] for n in names.splitlines() if n]

    def files(self):
        """The kit's files: project path -> bytes (HEAD, as committed)."""
        return {rel: show(self.path, "HEAD", f"{TEMPLATE}/{rel}") for rel in self.tracked(TEMPLATE)
                if rel != GITIGNORE and rel not in FENCE}

    def file_at(self, rev, rel):
        """A kit file at an older revision, before or after the move into template/."""
        for path in (f"{TEMPLATE}/{rel}", OLD_FENCE.get(rel), rel):
            if path:
                data = show(self.path, rev, path)
                if data is not None:
                    return data
        return None

    def fence(self, rev="HEAD"):
        return {rel: fence_entries(rel, self.file_at(rev, rel)) for rel in FENCE}

    def seeds(self):
        return {rel: show(self.path, "HEAD", f"{SEED}/{rel}") for rel in self.tracked(SEED)}

    def last_change(self, since, rel):
        """Committer time of the kit's last change to a file on main after `since` (0 if none)."""
        paths = [f"{TEMPLATE}/{rel}", rel] + ([OLD_FENCE[rel]] if rel in OLD_FENCE else [])
        stamp = out(self.path, "log", "--first-parent", "-1", "--format=%ct", f"{since}..HEAD", "--", *paths,
                    check=False)
        return int(stamp) if stamp else 0

    def commits(self, since):
        return out(self.path, "log", "--oneline", "--no-merges", f"{since}..HEAD", "--", TEMPLATE, SEED,
                   check=False).splitlines()


# ---------------------------------------------------------------- the fence

def fence_entries(rel, data):
    """The deny entries of a fence file, as strings."""
    if not data:
        return []
    doc = json.loads(data.decode("utf-8-sig"))
    if rel == CLAUDE_FENCE:
        return list(doc.get("permissions", {}).get("deny", []))
    found = []
    for rule in doc.get("permissions", {}).get("rules", []):
        if rule.get("effect") == "deny":
            found += [f"{rule.get('capability')}:{m}" for m in rule.get("match", [])]
    return found


def merge_fence(rel, project, kit, old_kit):
    """The project's fence file with the kit's entries added and the ones the kit dropped removed."""
    if project is None:
        return kit
    doc = json.loads(project.decode("utf-8-sig"))
    before = copy.deepcopy(doc)
    kit_entries = fence_entries(rel, kit)
    dropped = set(old_kit) - set(kit_entries)
    if rel == CLAUDE_FENCE:
        deny = doc.setdefault("permissions", {}).setdefault("deny", [])
        deny[:] = [e for e in deny if e not in dropped] + [e for e in kit_entries if e not in deny]
    else:
        rules = doc.setdefault("permissions", {}).setdefault("rules", [])
        kit_rules = [r for r in json.loads(kit.decode("utf-8-sig"))["permissions"]["rules"] if r.get("effect") == "deny"]
        for rule in rules:
            if rule.get("effect") == "deny":
                cap = rule.get("capability")
                rule["match"] = [m for m in rule.get("match", []) if f"{cap}:{m}" not in dropped]
        for kit_rule in kit_rules:
            mine = next((r for r in rules if r.get("effect") == "deny"
                         and r.get("capability") == kit_rule.get("capability")), None)
            if mine is None:
                rules.append(copy.deepcopy(kit_rule))
            else:
                mine["match"] += [m for m in kit_rule.get("match", []) if m not in mine["match"]]
    if doc == before:  # nothing to add or drop: keep the project's file byte for byte
        return project
    return (json.dumps(doc, indent=2) + "\n").encode()


def merge_gitignore(project, kit):
    have = (project or b"").decode("utf-8").splitlines()
    wanted = [line for line in kit.decode("utf-8").splitlines()
              if line.strip() and not line.startswith("#") and line not in have]
    if not wanted:
        return project
    base = (project or b"").decode("utf-8")
    if base and not base.endswith("\n"):
        base += "\n"
    return (base + ("\n" if base else "") + "# From the kit (factory-kit)\n" + "\n".join(wanted) + "\n").encode()


# ---------------------------------------------------------------- the project

class Project:
    def __init__(self, path):
        top = out(path, "rev-parse", "--show-toplevel", check=False)
        if not top:
            raise Stop(f"{Path(path).resolve()} is not inside a Git repository")
        self.path = Path(top).resolve()

    def lock(self):
        data = read(self.path, LOCK)
        return json.loads(data) if data else None

    def base(self):
        """The branch a sync starts from: origin/main if there is one, else the current commit."""
        has_origin = git(self.path, "rev-parse", "--verify", "-q", "origin/main", check=False).returncode == 0
        if has_origin:
            git(self.path, "fetch", "-q", "origin", check=False)
            return "origin/main"
        return "HEAD"

    def last_change(self, base, rel):
        stamp = out(self.path, "log", "--first-parent", "-1", "--format=%ct", base, "--", rel, check=False)
        return int(stamp) if stamp else 0

    def dirty(self):
        return out(self.path, "status", "--porcelain")


def project_owned(rel):
    return rel in PROJECT_FILES or any(rel.startswith(d) for d in PROJECT_DIRS)


# ---------------------------------------------------------------- the comparison

def plan(kit, project, lock, base, discard=()):
    """For each of the kit's files: what sync does. Returns (actions, notes)."""
    actions, notes = {}, {"project-only": [], "project-won": [], "kit-won": [], "kit-removed-kept": []}
    kit_files = kit.files()
    since = lock["revision"]
    for rel in sorted(set(kit_files) | set(lock["files"])):
        if project_owned(rel):
            continue
        k = kit_files.get(rel)
        lk = lock["files"].get(rel)
        p = read(project.path, rel)
        P, K = digest(p), digest(k)
        if rel in discard:  # the human gives up the project's change: take the kit's version
            if K is None and p is not None:
                actions[rel] = ("delete", None)
            elif K is not None and P != K:
                actions[rel] = ("write", k)
            continue
        if K is None:  # the kit removed it
            if P is not None and P != lk:
                notes["kit-removed-kept"].append(rel)
            elif p is not None:
                actions[rel] = ("delete", None)
            continue
        if P == K:
            continue
        if P == lk:  # only the kit changed it (or it is new)
            actions[rel] = ("write", k)
        elif K == lk:  # only the project changed it
            notes["project-only"].append(rel)
        else:  # both changed it: the change that reached main later wins
            mine, theirs = project.last_change(base, rel), kit.last_change(since, rel)
            if mine > theirs:
                notes["project-won"].append(rel)
            else:
                actions[rel] = ("write", k)
                notes["kit-won"].append(rel)
    return actions, notes


def new_lock(kit):
    return {"kit": kit.url, "revision": kit.rev,
            "files": {rel: digest(data) for rel, data in sorted(kit.files().items())},
            "fence": kit.fence()}


def adopt_lock(kit, rev):
    resolved = out(kit.path, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}", check=False)
    if not resolved:
        raise Stop(f"{rev} is not a commit in the kit clone {kit.path}")
    return {"kit": kit.url, "revision": resolved,
            "files": {rel: digest(kit.file_at(resolved, rel)) for rel in sorted(kit.files())},
            "fence": kit.fence(resolved)}


# ---------------------------------------------------------------- what the setup still lacks

def gh_api(host, path):
    """GET `path` from GitHub's API through `gh`: (HTTP status or None, the body as JSON or text).
    A status of None means `gh` could not ask at all (not installed, not signed in, no network)."""
    try:
        done = subprocess.run(["gh", "api", "--hostname", host, path], capture_output=True)
    except OSError:
        return None, "gh is not installed"
    text = done.stdout.decode("utf-8", errors="replace")
    try:
        body = json.loads(text) if text.strip() else None
    except ValueError:
        body = text
    if done.returncode == 0:
        return 200, body
    err = done.stderr.decode("utf-8", errors="replace").strip()
    code = re.search(r"HTTP (\d{3})", err)
    message = body.get("message") if isinstance(body, dict) else None
    return (int(code.group(1)) if code else None), (message or err.splitlines()[-1] if err else message or "no answer")


def github_repo(root):
    """(host, owner, repo) from the project's `origin`, or None."""
    url = out(root, "remote", "get-url", "origin", check=False)
    m = re.match(r"(?:https?://(?:[^@/]+@)?|ssh://(?:[^@/]+@)?|[^@/]+@)([^/:]+)(?::\d+)?[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return m.groups() if m else None


def setup_open(root, github=True):
    """What the project's one-time setup (RUNBOOK.md) still lacks, one line each. Never a failure:
    a project may run without Actions or branch protection, but someone must know it does."""
    root = Path(root)
    opens = []
    skills = [root / d for d in SKILL_DIRS if (root / d).is_dir()]
    linked = sorted(f"{p.relative_to(root).as_posix()}" for d in skills for p in d.iterdir() if p.is_symlink())
    if linked:
        opens.append(f"{len(linked)} skill folder(s) are symlinks (first: {linked[0]}), most likely into .agents/, "
                     "which Git ignores: a clone would get broken links. Install BMAD again with `--copy` "
                     "(RUNBOOK.md, One-time setup, step 2).")
    if not (root / "_bmad").is_dir() or not any((d / "bmad-build" / "SKILL.md").is_file() for d in skills):
        opens.append("BMAD is not installed (RUNBOOK.md, One-time setup, step 2).")
    else:
        initiative, problem = None, None
        data = read(root, BMAD_USER_CONFIG)
        if data:
            try:
                import tomllib
                core = tomllib.loads(data.decode("utf-8")).get("core", {})
                initiative = core.get("active_initiative") if isinstance(core, dict) else None
            except (ImportError, ValueError) as e:
                problem = f"{BMAD_USER_CONFIG} cannot be read ({e})"
        if problem:
            opens.append(problem + ".")
        elif not initiative:
            opens.append(f"No active BMAD initiative. Before planning, you (not the agent: `_bmad/custom/` is fenced) "
                         f"put `[core]` and `active_initiative = \"initiative-<name>\"` in {BMAD_USER_CONFIG}. "
                         "Git ignores it, so every clone needs its own (RUNBOOK.md, Plan the product).")
    if not github:
        return opens
    repo = github_repo(root)
    if not repo:
        return opens + ["Could not ask GitHub (no GitHub `origin`): check Actions, the labels and branch protection "
                        "by hand (RUNBOOK.md, One-time setup)."]
    host, owner, name = repo
    base = f"repos/{owner}/{name}"
    status, body = gh_api(host, f"{base}/actions/permissions")
    if status is None:
        return opens + [f"Could not ask GitHub ({body}): check Actions, the labels and branch protection by hand "
                        "(RUNBOOK.md, One-time setup)."]
    if status == 200 and isinstance(body, dict) and body.get("enabled") is False:
        opens.append("GitHub Actions is off for this repository: no workflow runs, so no pull request gets `gates`, "
                     "`protected-paths` or `scope-guard` until you run the factory judge (`python harness/judge/judge.py "
                     "--once`). See RUNBOOK.md, Without GitHub Actions. Do not switch Actions on without approval.")
    elif status != 200:
        opens.append(f"Could not read whether GitHub Actions may run (HTTP {status}: {body}).")
    status, body = gh_api(host, f"{base}/labels?per_page=100")
    if status == 200 and isinstance(body, list):
        have = {label.get("name") for label in body if isinstance(label, dict)}
        missing = [label for label in LABELS if label not in have]
        if missing:
            opens.append("Missing label(s): " + ", ".join(missing) + " (RUNBOOK.md, One-time setup, step 4).")
    else:
        opens.append(f"Could not read the labels (HTTP {status}: {body}).")
    status, body = gh_api(host, f"{base}/branches/main/protection")
    if status == 200 and isinstance(body, dict):
        checks = (body.get("required_status_checks") or {})
        required = set(checks.get("contexts") or []) | {c.get("context") for c in checks.get("checks") or []}
        missing = [c for c in REQUIRED_CHECKS if c not in required]
        if missing:
            opens.append("`main` is protected but does not require " + ", ".join(missing)
                         + " (RUNBOOK.md, One-time setup, step 5; without Actions, once the judge has posted them).")
    elif status == 404:
        opens.append("`main` is not protected (RUNBOOK.md, One-time setup, step 5).")
    elif status == 403:
        opens.append(f"Branch protection is not available here ({body}). On a free plan a private repository's rules "
                     "are not enforced: the checks still show, and you must respect them yourself.")
    else:
        opens.append(f"Could not read branch protection on `main` (HTTP {status}: {body}).")
    return opens


# ---------------------------------------------------------------- doctor

def protected_paths(guards_data):
    pattern = json.loads(guards_data)["protected-paths"]["pattern"]
    inner = re.fullmatch(r"\^\((.*)\)", pattern)
    if not inner:
        raise Stop(f"{GUARDS}: the protected-paths pattern is not of the form ^(a|b|...)")
    return [p.replace("\\", "") for p in inner.group(1).split("|")]


def doctor(root, kit=None, lock=None, quiet=False, setup=False, github=True):
    """(failures, warnings) for the project at `root`. With `setup`, also prints what the project's
    setup still lacks (`setup_open`); those lines never fail it."""
    failures, warnings = [], []
    guards = read(root, GUARDS)
    paths = protected_paths(guards) if guards else []
    if not guards:
        failures.append(f"{GUARDS} is missing")
    claude = fence_entries(CLAUDE_FENCE, read(root, CLAUDE_FENCE))
    kiro = [e.split(":", 1)[1] for e in fence_entries(KIRO_FENCE, read(root, KIRO_FENCE)) if e.startswith("fs_write:")]
    for p in paths:
        glob = p + "**" if p.endswith("/") else p
        if f"Edit(/{glob})" not in claude:
            failures.append(f"{CLAUDE_FENCE} does not deny Edit(/{glob}), a protected path")
        if glob not in kiro:
            failures.append(f"{KIRO_FENCE} does not deny fs_write on {glob}, a protected path")
    for pair in SKILL_PAIRS:
        skills = [normal(read(root, s)) for s in pair]
        if None in skills or skills[0] != skills[1]:
            failures.append(f"{pair[1]} must be a copy of {pair[0]}")
    owners = (read(root, CODEOWNERS) or b"").decode("utf-8", errors="replace").split()
    for p in paths:
        if "/" + p not in owners:
            warnings.append(f"{CODEOWNERS} has no line for /{p} (a protected path)")
    if kit is not None and lock is not None and kit.phase == "mature":
        for rel, h in lock["files"].items():
            if not project_owned(rel) and h is not None and digest(read(root, rel)) != h:
                failures.append(f"{rel} differs from the kit's version. The kit is mature: open an issue in "
                                f"factory-kit, or run `kit.py sync --discard {rel}`.")
    opens = setup_open(root, github) if setup and not quiet else []
    if not quiet:
        for w in warnings:
            print(f"warning: {w}")
        for f in failures:
            print(f"FAIL: {f}")
        for o in opens:
            print(f"open: {o}")
        print("doctor: " + ("OK" if not failures else f"{len(failures)} failure(s)")
              + (f", {len(warnings)} warning(s)" if warnings else "")
              + (f", {len(opens)} open setup step(s)" if opens else ""))
    return failures, warnings


# ---------------------------------------------------------------- commands

def cmd_init(kit, project, a):
    if read(project.path, LOCK):
        raise Stop(f"{LOCK} exists: this project already has the factory. Use `kit.py sync`.")
    files = kit.files()
    taken = [rel for rel in list(files) + list(FENCE) if (project.path / rel).exists()]
    if taken:
        raise Stop("These files exist already, so init would overwrite them:\n  " + "\n  ".join(taken)
                   + "\nFor a project made before kit.py, use `kit.py sync --adopt <kit revision>`.")
    origin = out(project.path, "remote", "get-url", "origin", check=False)
    host = a.host or (re.match(r"(?:https?://|git@)([^/:]+)", origin).group(1) if re.match(r"(?:https?://|git@)", origin)
                      else "github.com")
    names = {"__OWNER__": a.owner, "__PROJECT__": a.project or project.path.name, "__HOST__": host}
    for rel, data in files.items():
        write(project.path, rel, data)
    for rel in FENCE:
        write(project.path, rel, kit.file_at("HEAD", rel))
    write(project.path, GITIGNORE, merge_gitignore(read(project.path, GITIGNORE), show(kit.path, "HEAD", f"{TEMPLATE}/{GITIGNORE}")))
    for rel, data in kit.seeds().items():
        if (project.path / rel).exists():
            print(f"kept your {rel}")
            continue
        text = data.decode("utf-8")
        for k, v in names.items():
            text = text.replace(k, v)
        write(project.path, rel, text.encode("utf-8"))
    write(project.path, LOCK, (json.dumps(new_lock(kit), indent=2) + "\n").encode())
    print(f"installed the kit at {kit.rev[:7]}: {len(files)} kit files, the fence, {len(kit.seeds())} seeds, {LOCK}")
    failures, _ = doctor(project.path, kit, None, setup=True)
    return 1 if failures else 0


def cmd_status(kit, project, a):
    lock = project.lock()
    if not lock:
        raise Stop(f"No {LOCK}: run `kit.py init` for a new project, or `kit.py sync --adopt <kit revision>`.")
    print(f"project at kit {lock['revision'][:7]}, kit main at {kit.rev[:7]} (phase: {kit.phase})")
    commits = kit.commits(lock["revision"])
    print(f"{len(commits)} kit commit(s) not in this project" + (":" if commits else ""))
    for c in commits:
        print(f"  {c}")
    actions, notes = plan(kit, project, lock, "HEAD")
    for rel, (what, _) in sorted(actions.items()):
        print(f"  would {'update' if what == 'write' else 'delete'} {rel}")
    for rel in notes["project-only"] + notes["project-won"]:
        print(f"  not in the kit yet: {rel}")
    return 0


def cmd_sync(kit, project, a):
    kit.check_clean()
    if project.dirty():
        raise Stop("The project has uncommitted changes. Commit or stash them first.")
    lock = adopt_lock(kit, a.adopt) if a.adopt else project.lock()
    if not lock:
        raise Stop(f"No {LOCK}. For a project made before kit.py, run `kit.py sync --adopt <kit revision it matches>`.")
    base = project.base()
    discard = set(a.discard or ())
    # Compare against the branch the update starts from, not whatever is checked out.
    branch = f"factory/sync-{kit.rev[:7]}"
    if git(project.path, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False).returncode == 0:
        raise Stop(f"The branch {branch} exists already. Delete it, or finish the update it holds.")
    previous = out(project.path, "rev-parse", "--abbrev-ref", "HEAD")
    git(project.path, "switch", "-q", "-c", branch, base)

    def back_out(message):
        git(project.path, "switch", "-q", previous if previous != "HEAD" else "-")
        git(project.path, "branch", "-q", "-D", branch)
        return message

    actions, notes = plan(kit, project, lock, "HEAD", discard)
    if kit.phase == "mature" and notes["project-only"]:
        raise Stop(back_out("The kit is mature, and the project changed these kit files:\n  "
                            + "\n  ".join(notes["project-only"]) + "\nOpen an issue in factory-kit for each change, "
                            "then run `kit.py sync --discard <file>` to take the kit's version."))
    fence_writes = {}
    for rel in FENCE:
        merged = merge_fence(rel, read(project.path, rel), kit.file_at("HEAD", rel), lock["fence"].get(rel, []))
        if merged != read(project.path, rel):
            fence_writes[rel] = merged
    ignore = merge_gitignore(read(project.path, GITIGNORE), show(kit.path, "HEAD", f"{TEMPLATE}/{GITIGNORE}"))
    lock_new = new_lock(kit)
    if not actions and not fence_writes and ignore == read(project.path, GITIGNORE) and lock_new == project.lock():
        back_out("")
        print("nothing to do: the project has the kit's current version")
        for rel in notes["project-only"]:
            print(f"  not in the kit yet: {rel}")
        return 0
    for rel, (what, data) in actions.items():
        if what == "write":
            write(project.path, rel, data)
        else:
            (project.path / rel).unlink()
    for rel, data in fence_writes.items():
        write(project.path, rel, data)
    if ignore != read(project.path, GITIGNORE):
        write(project.path, GITIGNORE, ignore)
    write(project.path, LOCK, (json.dumps(lock_new, indent=2) + "\n").encode())
    failures, warnings = doctor(project.path, kit, lock_new, quiet=True)
    body = pr_body(kit, lock, actions, fence_writes, notes, failures, warnings, bool(a.adopt))
    gitdir = Path(out(project.path, "rev-parse", "--absolute-git-dir"))
    (gitdir / "kit-sync-pr.md").write_text(body, encoding="utf-8")
    print(f"on branch {branch}: {len(actions)} kit file(s), {len(fence_writes)} fence file(s) changed")
    for rel in notes["kit-won"]:
        print(f"  both changed {rel}: the kit's change reached main later and wins")
    for rel in notes["project-won"]:
        print(f"  both changed {rel}: the project's change reached main later and stays (not in the kit yet)")
    for rel in notes["project-only"]:
        print(f"  not in the kit yet: {rel}")
    for f in failures:
        print(f"FAIL: {f}")
    for w in warnings:
        print(f"warning: {w}")
    print(f"pull request body: {gitdir / 'kit-sync-pr.md'}")
    print("Nothing is committed. Review with `git status`, then commit, push and open the pull request.")
    return 1 if failures else 0


def pr_body(kit, lock, actions, fence_writes, notes, failures, warnings, adopted):
    lines = [f"Takes the kit (`factory-kit`) from `{lock['revision'][:7]}` to `{kit.rev[:7]}`"
             + (" (first sync, adopted)" if adopted else "") + ". Made with `kit.py sync`.", "",
             "**Needs a human:** the label `human-judge-change`.", ""]
    commits = kit.commits(lock["revision"])
    if commits:
        lines += ["## Kit commits", ""] + [f"- {c}" for c in commits] + [""]
    if actions or fence_writes:
        lines += ["## Files", ""]
        lines += [f"- {'updated' if w == 'write' else 'deleted'}: `{r}`" for r, (w, _) in sorted(actions.items())]
        lines += [f"- fence merged: `{r}`" for r in sorted(fence_writes)] + [""]
    for key, title in (("kit-won", "Changed on both sides; the kit's change reached `main` later and won"),
                       ("project-won", "Changed on both sides; the project's change reached `main` later and stays"),
                       ("project-only", "Changed in this project, not in the kit yet"),
                       ("kit-removed-kept", "Removed from the kit, kept here because this project changed them")):
        if notes[key]:
            lines += [f"## {title}", ""] + [f"- `{r}`" for r in notes[key]] + [""]
    lines += ["## kit.py doctor", ""] + ([f"- FAIL: {f}" for f in failures] + [f"- warning: {w}" for w in warnings]
                                         or ["- OK"]) + [""]
    return "\n".join(lines)


def cmd_doctor(kit, project, a):
    failures, _ = doctor(project.path, kit, project.lock(), setup=True, github=not a.offline)
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Install the factory in a project and keep it up to date.")
    p.add_argument("--kit", default=str(KIT), help="the kit clone (default: the one this script is in)")
    p.add_argument("--project", dest="root", default=".", help="the project (default: the current folder)")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="install the factory in a new project")
    i.add_argument("--owner", required=True, help="the GitHub user or team for CODEOWNERS")
    i.add_argument("--project", dest="name", help="the project's name (default: its folder's name)")
    i.add_argument("--host", help="the GitHub host (default: from origin, else github.com)")
    sub.add_parser("status", help="what the kit has that the project does not")
    s = sub.add_parser("sync", help="take the kit's changes, on a new branch")
    s.add_argument("--adopt", metavar="REV", help="first sync of a project made before kit.py: the kit revision it matches")
    s.add_argument("--discard", metavar="FILE", action="append", help="take the kit's version of this file")
    d = sub.add_parser("doctor", help="check the fence, the lap and triage skills and CODEOWNERS; list open setup steps")
    d.add_argument("--offline", action="store_true", help="do not ask GitHub about Actions, labels or branch protection")
    a = p.parse_args(argv)
    if a.cmd == "init":
        a.project = a.name
    try:
        kit, project = Kit(a.kit), Project(a.root)
        return {"init": cmd_init, "status": cmd_status, "sync": cmd_sync, "doctor": cmd_doctor}[a.cmd](kit, project, a)
    except Stop as e:
        print(f"kit.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
