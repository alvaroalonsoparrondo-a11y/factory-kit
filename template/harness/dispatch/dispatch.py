#!/usr/bin/env python3
"""The factory's queue and orchestrator: claims ready tickets, starts laps, routes them, closes them.

Part of the judge. Human-owned. Standard library only (Python 3.11+).

  python harness/dispatch/dispatch.py tick                 one pass
  python harness/dispatch/dispatch.py tick --dry-run       say what one pass would do; change nothing
  python harness/dispatch/dispatch.py tick --loop 5        a pass every 5 minutes until Ctrl+C
  python harness/dispatch/dispatch.py tick --no-agents     claim, route and close, but a human runs every lap
  python harness/dispatch/dispatch.py pause | unpause      stop or resume starting new laps; routing goes on
  python harness/dispatch/dispatch.py release <ref>        retry a lap that was stopped for you, after you fixed it
  python harness/dispatch/dispatch.py forget <ref>         drop a lap from the dispatcher's memory
  python harness/dispatch/dispatch.py verify-fence         check that a headless lap obeys the fence

GitHub: FACTORY_DISPATCH_TOKEN, else GITHUB_TOKEN, else `gh auth token`. None of them reaches a lap.
The host (github.com or GitHub Enterprise) comes from `origin`; GITHUB_API_URL overrides the API root.

A local script cannot receive webhooks, so it polls: the events are the differences between two passes.
Each pass reads ticket state the way the live board does (`harness/board/serve.py`: Git, GitHub, the
BMAD files, every worktree's plans, lap signals and quiet time), keeps the laps it started in
`.factory/dispatch-state.json` in the main checkout (ignored by Git), and appends one line per closed
lap to `.factory/lap-reports.log`. Only one pass runs at a time (`.factory/dispatch.lock`).

Nothing here reads hidden scenarios: where a project has a `holdouts` check, a failure is known only by its ID.
"""
import argparse
import contextlib
import ctypes
import datetime as dt
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "board"))
import board  # noqa: E402  (ticket state from Git, GitHub and the BMAD files)
import serve  # noqa: E402  (the live board's snapshot: worktrees, lap signals, quiet time)
import lap_round  # noqa: E402  (the lap's round budget, shared by every check: harness/rounds.json)
import triage  # noqa: E402  (each ticket's route before its lap: docs/triage/<ref>.json)

# A clean merge of main is not a round (it says nothing about the ticket), but a lap that falls behind
# again and again is spending without progress: after this many, it stops for the human.
MAX_MOVED_ROUNDS = 3
# The factory judge begins a red `gates` the change did not cause with this (a machine failure, or main red
# alone too): no fix round for it, it goes to the human. See harness/judge/classify.py.
NOT_THIS_CHANGE = "Not this change:"
JUDGE_MARKER = "<!-- factory-judge:gates -->"  # the factory judge's failing-gates comment (harness/judge/judge.py)
DEFAULT_CAP = 2
BASE_PORT = 8090  # 8080 is the human's app, 8081 a hand-started worktree lap
QUIET_MINUTES = 60  # a running lap with no file change for this long has probably died without ending
LIMIT_RETRY_MINUTES = 30
MAX_LIMIT_RETRIES = 6
# A usage limit or an outage says nothing about the ticket: the lap is resumed later, not stopped.
LIMIT_RE = re.compile(r"usage limit|hit your limit|limit reached|rate[ _-]?limit|overloaded|\b529\b|resets? (at|in) ",
                      re.I)
# Every required check except the guards gets fix rounds (`gates`, and `holdouts` where a project has it);
# a red guard is a human's call: label it or send it back.
FIXABLE = tuple(c for c in board.CHECKS if c not in board.GUARDS)
TOKEN_VARS = ("FACTORY_DISPATCH_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")

# Headless permission mode. `dontAsk` refuses every tool call not allowed below, and the deny rules in
# .claude/settings.json are checked before any allow rule, so the fence still holds. Never
# bypassPermissions. `verify-fence` checks this on a scratch repository.
PERMISSION_MODE = "dontAsk"
ALLOWED_TOOLS = "Bash Read Edit Write Glob Grep Skill Agent TodoWrite TaskCreate TaskUpdate TaskList TaskGet"
# A triage only reads: no shell, no edits. The dispatcher records its answer on main.
TRIAGE_TOOLS = "Read Glob Grep Skill"
TRIAGE_CAP = 1  # triages at once; short and read-only, they do not count against the lap cap

TRIAGE_PROMPT = (
    "triage {ref}\n\nYou were started by the factory dispatcher, headless (FACTORY_DISPATCHED=1), in a checkout "
    "of origin/main. Use the triage skill on ticket {ref}. Nobody can answer a question, and you may not change "
    "anything. Your final message is the skill's JSON object and nothing else."
)

HEADLESS_NOTE = (
    "You were started by the factory dispatcher, headless (FACTORY_DISPATCHED=1): the ticket is already "
    "claimed and `story/{ref}` is checked out here; use PORT from the environment for the gates. Nobody can "
    "answer a question. Where the lap skill says to ask, confirm or wait, run `python harness/board/lap_signal.py "
    "{ref} waiting <kind> \"<what you need>\"` and end; the dispatcher shows it to the human."
)


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- the world outside

class Repo:
    """The Git side. `root` is any checkout of the repository."""

    def __init__(self, root):
        self.root = str(root)

    def _git(self, *args, cwd=None, check=True):
        done = subprocess.run(["git", *args], cwd=cwd or self.root, capture_output=True, text=True,
                              encoding="utf-8")
        if check and done.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
        return done

    def fetch(self):
        self._git("fetch", "--quiet", "--prune", "origin")

    def sha(self, ref):
        return self._git("rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False).stdout.strip() or None

    def contains(self, ancestor, ref):
        return self._git("merge-base", "--is-ancestor", ancestor, ref, check=False).returncode == 0

    def file_on_main(self, path):
        return self._git("cat-file", "-e", f"origin/main:{path}", check=False).returncode == 0

    def origin(self):
        """(owner/name, server) from the `origin` URL."""
        url = self._git("remote", "get-url", "origin").stdout.strip()
        m = re.match(r"^(?:https?://([^/]+)/|git@([^:]+):)([^/]+/[^/]+?)(?:\.git)?/?$", url)
        if not m:
            raise RuntimeError(f"cannot read owner/name from origin {url}")
        return m.group(3), f"https://{m.group(1) or m.group(2)}"

    def main_checkout(self):
        """The first worktree Git lists is the main checkout."""
        out = self._git("worktree", "list", "--porcelain").stdout
        return Path(out.splitlines()[0].removeprefix("worktree ").strip())

    def main_checkout_state(self):
        path = self.main_checkout()
        branch = self._git("branch", "--show-current", cwd=path).stdout.strip()
        dirty = bool(self._git("status", "--porcelain", cwd=path).stdout.strip())
        return branch, dirty

    def pull_main_checkout(self):
        self._git("pull", "--ff-only", "--quiet", cwd=self.main_checkout())

    def add_worktree(self, path, branch):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "-b", branch, str(path), f"origin/{branch}")

    def remove_worktree(self, path, branch):
        if Path(path).exists():
            self._git("worktree", "remove", str(path))
        self._git("branch", "-D", branch, check=False)

    def add_detached_worktree(self, path, sha):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "--quiet", "--detach", str(path), sha)

    def remove_detached_worktree(self, path):
        self._git("worktree", "remove", "--force", str(path), check=False)

    def _commit_to_main(self, prefix, change, folder, message):
        """Run `change(tmp)` in a throwaway detached worktree of origin/main, commit what it changed under
        `folder` and push it straight onto main, so no checkout is disturbed. Never force-pushes.
        The same code records a hand triage (`triage.py record --push`)."""
        triage.commit_to_main(self.root, prefix, change, folder, f"{message}\n\nBy the factory dispatcher.")

    def mark_done(self, ticket, ref, pr):
        """Commit `status: done` in the ticket's plan straight onto main, as the lap's closing step does."""
        initiative = ticket["source"].split("/")[1]

        def change(tmp):
            tool = tmp / ".claude" / "skills" / "bmad-agent-po" / "scripts" / "tickets.py"
            done = subprocess.run([sys.executable, str(tool), "--project-root", str(tmp), "mark", initiative, ref,
                                   "done"], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
            if done.returncode != 0:
                raise RuntimeError(f"tickets.py mark: {(done.stdout + done.stderr).strip()[-300:]}")

        self._commit_to_main(f"mark-{ref}-", change, board.BMAD_DIR,
                             f"Mark ticket {ref} done: {ticket['title']} merged in {pr}")

    def triage_record(self, decision, ref, sha):
        """The decision as a record, stamped against the commit the triage read. Raises ValueError."""
        ticket, plans = triage._load(self.root, sha, ref)
        return triage.build_record(decision, self.root, sha, ticket, plans)

    def commit_triage(self, record):
        """Commit docs/triage/<ref>.json straight onto main."""
        self._commit_to_main(f"triage-{record['ref']}-", lambda tmp: triage.write_record(tmp, record),
                             triage.RECORD_DIR, f"Triage ticket {record['ref']}: {record['state']}")


def _gh_api(args):
    done = subprocess.run(["gh", "api", *args], capture_output=True, text=True, encoding="utf-8", timeout=120)
    return done.returncode, done.stdout, done.stderr


class GitHub:
    """Reads through the live board's client (Python HTTPS, falling back to `gh api` on a certificate
    error); writes the one thing the dispatcher writes, a branch, the same way."""

    def __init__(self, repo, token, reader, api="https://api.github.com"):
        self.repo, self.token, self.reader, self.api = repo, token, reader, api.rstrip("/")

    def get(self, path, key=None):
        return self.reader.get(path, key)

    def create_ref(self, branch, sha):
        """Claim: True when the branch was created, False when it already exists (422)."""
        body = {"ref": f"refs/heads/{branch}", "sha": sha}
        if self.token:
            req = urllib.request.Request(f"{self.api}/repos/{self.repo}/git/refs", data=json.dumps(body).encode(),
                                         method="POST", headers={
                                             "Authorization": f"Bearer {self.token}",
                                             "Accept": "application/vnd.github+json",
                                             "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "factory-dispatch"})
            try:
                with urllib.request.urlopen(req, timeout=30):
                    return True
            except urllib.error.HTTPError as e:
                if e.code == 422:
                    return False
                raise
            except urllib.error.URLError:
                if not shutil.which("gh"):
                    raise
        code, out, err = _gh_api(["-X", "POST", f"repos/{self.repo}/git/refs", "-f", f"ref={body['ref']}",
                                  "-f", f"sha={sha}"])
        if code == 0:
            return True
        if "422" in err or "already exists" in (out + err):
            return False
        raise RuntimeError(f"claim {branch}: {err.strip()}")

    def failing_summary(self, sha, check):
        """What a fix round gets to read: the holdout IDs only, or the gates check's output and log tail."""
        if check == "holdouts":
            for st in self.get(f"/commits/{sha}/status").get("statuses", []):
                if st["context"] == "holdouts":
                    ids = sorted(set(re.findall(r"H-\d+", st.get("description") or "")))
                    return "failed: " + (" ".join(ids) if ids else "(no ID given)")
            return "failed (no description)"
        runs = [r for r in self.get(f"/commits/{sha}/check-runs", key="check_runs") if r["name"] == check]
        if not runs:
            return self._judge_comment(sha, check) or "(no check run found)"
        run = max(runs, key=lambda r: r.get("id", 0))
        out = run.get("output") or {}
        parts = [p for p in (out.get("title"), out.get("summary"), out.get("text")) if p]
        log = self._job_log_tail(run["id"])
        if log:
            parts.append("Last lines of the job log:\n" + log)
        parts.append(f"Details: {run.get('html_url', '')}")
        return "\n\n".join(parts)[-6000:]

    def _judge_comment(self, sha, check):
        """Without Actions, the factory judge (harness/judge/judge.py) puts the failing tail in a comment."""
        if check != "gates":
            return None
        try:
            for pr in self.get(f"/commits/{sha}/pulls"):
                for c in self.get(f"/issues/{pr['number']}/comments"):
                    body = c.get("body") or ""
                    if JUDGE_MARKER in body and f"<!-- sha:{sha} -->" in body:
                        return body.split(f"<!-- sha:{sha} -->", 1)[1].strip()[-6000:]
        except (RuntimeError, urllib.error.URLError):
            return None
        return None

    def _job_log_tail(self, job_id, lines=80):
        text = ""
        if shutil.which("gh"):
            code, out, _ = _gh_api([f"repos/{self.repo}/actions/jobs/{job_id}/logs"])
            text = out if code == 0 else ""
        elif self.token:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k):
                    return None
            req = urllib.request.Request(f"{self.api}/repos/{self.repo}/actions/jobs/{job_id}/logs",
                                         headers={"Authorization": f"Bearer {self.token}", "User-Agent": "factory-dispatch"})
            try:
                urllib.request.build_opener(NoRedirect).open(req, timeout=30)
            except urllib.error.HTTPError as e:
                where = e.headers.get("Location")
                if where:  # a signed storage URL: no token goes there
                    try:
                        with urllib.request.urlopen(where, timeout=60) as resp:
                            text = resp.read().decode("utf-8", "replace")
                    except urllib.error.URLError:
                        pass
            except urllib.error.URLError:
                pass
        return "\n".join(re.sub(r"^\S+Z ", "", line) for line in text.splitlines()[-lines:])


class NoGitHub(serve.NoGitHub):
    """No token and no `gh`: the board sees no pull requests and nothing can be claimed."""

    def create_ref(self, branch, sha):
        raise RuntimeError("no GitHub access: set FACTORY_DISPATCH_TOKEN or run `gh auth login`")

    def failing_summary(self, sha, check):
        return "(no GitHub access: the failing output could not be read)"


def collect(repo, gh, server, quiet_minutes):
    """The live board's snapshot, with tickets and main's plans always from origin/main."""
    snap = serve.Source(repo.root, gh.repo, gh, server, quiet_seconds=quiet_minutes * 60).snapshot()
    files = board.bmad_files(repo.root, "origin/main")
    snap["tickets"] = board.read_tickets(files, snap["problems"])
    snap["plans"]["main"] = board.read_plans(files)
    snap["triage"] = triage.statuses(repo.root, "origin/main", snap["tickets"], snap["plans"]["main"])
    return snap, files


def agent_env(port, ref):
    """The agent's environment: no GitHub token of any kind, its own port."""
    env = {k: v for k, v in os.environ.items() if k not in TOKEN_VARS}
    env.update({"PORT": str(port), "FACTORY_DISPATCHED": "1", "FACTORY_LAP_REF": ref})
    return env


def claude_argv(prompt, session, model=None, resume=False, tools=ALLOWED_TOOLS):
    exe = shutil.which("claude") or "claude"
    argv = [exe, "-p", prompt, "--permission-mode", PERMISSION_MODE, "--allowedTools", tools,
            "--resume" if resume else "--session-id", session]
    if model:
        argv += ["--model", model]
    return argv


def fence_rules(root):
    """The deny rules of the fence in `root`, or None when the settings cannot be read."""
    try:
        data = json.loads((Path(root) / ".claude" / "settings.json").read_text(encoding="utf-8"))
        return list((data.get("permissions") or {}).get("deny") or [])
    except (OSError, ValueError):
        return None


class Runner:
    """Starts a stage as a detached process that outlives the dispatcher, and tells if it still runs."""

    def start(self, argv, cwd, env, log, exit_file):
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        Path(exit_file).unlink(missing_ok=True)
        wrapper = [sys.executable, str(Path(__file__).resolve()), "_stage", "--log", str(log),
                   "--exit-file", str(exit_file), "--", *argv]
        kw = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kw["start_new_session"] = True
        return subprocess.Popen(wrapper, **kw).pid

    def alive(self, pid):
        if not pid:
            return False
        if os.name == "nt":
            k32 = ctypes.windll.kernel32
            handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            code = ctypes.c_ulong()
            k32.GetExitCodeProcess(handle, ctypes.byref(code))
            k32.CloseHandle(handle)
            return code.value == 259  # STILL_ACTIVE
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False

    @staticmethod
    def exit_code(exit_file):
        try:
            return int(Path(exit_file).read_text().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def log_tail(log, chars=4000):
        try:
            return Path(log).read_text(encoding="utf-8", errors="replace")[-chars:]
        except OSError:
            return ""


class Store:
    """In-flight runs, lap reports, the pause switch and the one-pass lock, under `.factory/`."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = self.folder / "dispatch-state.json"

    def load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"runs": {}}

    def _ensure(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        ignore = self.folder / ".gitignore"
        if not ignore.exists():
            ignore.write_text("# Local dispatcher state; never committed.\n*\n", encoding="utf-8")

    def save(self, state):
        self._ensure()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def report(self, line):
        self._ensure()
        with open(self.folder / "lap-reports.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def paused(self):
        return (self.folder / "PAUSE").exists()

    def set_paused(self, on):
        self._ensure()
        if on:
            (self.folder / "PAUSE").write_text("No new laps; running laps are still routed and closed.\n",
                                               encoding="utf-8")
        else:
            (self.folder / "PAUSE").unlink(missing_ok=True)

    @contextlib.contextmanager
    def single_flight(self):
        """True for the one process holding the OS lock, False for the rest. The lock dies with its
        process, so a killed pass never wedges later ones (from the Archon factory, seen live)."""
        self._ensure()
        handle = open(self.folder / "dispatch.lock", "a+", encoding="utf-8")
        try:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return
            yield True
        finally:
            handle.close()


# --------------------------------------------------------------------------- reading the plan

def shared_paths(files):
    """Top-level `shared = [...]` of every epic tickets.toml: files any ticket may touch."""
    out = set()
    for path, text in files.items():
        if path.endswith("/tickets.toml"):
            try:
                out.update(str(s) for s in tomllib.loads(text).get("shared", []))
            except tomllib.TOMLDecodeError:
                pass
    return out


def _literal_prefix(pattern):
    m = re.search(r"[*?\[]", pattern)
    return pattern[:m.start()] if m else pattern


def patterns_overlap(a, b):
    """Could a path match both? Conservative: when unsure, yes."""
    a, b = a.strip().removeprefix("./"), b.strip().removeprefix("./")
    if a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
        return True
    pa, pb = _literal_prefix(a), _literal_prefix(b)
    wild_a, wild_b = pa != a, pb != b
    if not wild_a and not wild_b:
        return False
    if wild_a and wild_b:
        return pa.startswith(pb) or pb.startswith(pa)
    literal, prefix = (a, pb) if not wild_a else (b, pa)
    return literal.startswith(prefix)


def touches_overlap(t1, t2, shared):
    """Two tickets clash unless both list `touches` and no non-shared pattern of one overlaps the other's."""
    if t1 is None or t2 is None:
        return True
    p1 = [p for p in t1 if p not in shared]
    p2 = [p for p in t2 if p not in shared]
    return any(patterns_overlap(a, b) for a in p1 for b in p2)


def check_done_when(repo, done_when):
    """(met, problem). `file:<path>`: the file is on origin/main."""
    kind, _, arg = done_when.partition(":")
    if kind == "file" and arg:
        return repo.file_on_main(arg.strip()), None
    return False, f"unknown done_when `{done_when}` (known: file:<path>)"


# --------------------------------------------------------------------------- one pass

class Dispatcher:
    def __init__(self, repo, gh, runner, store, *, server="https://github.com", cap=DEFAULT_CAP,
                 dry_run=False, agents=True, allow_no_fence=False, model=None, quiet_minutes=QUIET_MINUTES,
                 collect_fn=None, fence=None, worktree_root=None, clock=time.time):
        self.repo, self.gh, self.runner, self.store = repo, gh, runner, store
        self.server, self.cap, self.dry_run, self.model = server.rstrip("/"), cap, dry_run, model
        self.agents, self.allow_no_fence, self.quiet_minutes = agents, allow_no_fence, quiet_minutes
        self.collect = collect_fn or (lambda: collect(repo, gh, self.server, quiet_minutes))
        self.fence = fence if fence is not None else (lambda: fence_rules(repo.main_checkout()))
        self.worktree_root = Path(worktree_root) if worktree_root else None
        self.clock = clock

    def _compare(self, branch):
        return f"{self.server}/{self.gh.repo}/compare/main...{branch}?expand=1"

    def _worktree_path(self, ref, kind="story"):
        base = self.worktree_root or (self.repo.main_checkout().parent / f"{self.gh.repo.split('/')[-1]}-wt")
        return base / f"{kind}-{ref}"

    # ---- the pass

    def tick(self):
        if not self.dry_run:
            self.repo.fetch()
        snapshot, files = self.collect()
        derived = board.derive(snapshot)
        tickets = {t.get("ref", t["id"]): t for t in snapshot["tickets"]}
        rows = {r["ref"]: r for e in derived["epics"] for r in e["rows"]}
        main_plans = {p["ticket"]: p for p in snapshot["plans"].get("main", [])}
        state = self.store.load()
        runs = state.setdefault("runs", {})
        shared = shared_paths(files)
        rep = {"ready": [], "claimed": [], "started": [], "running": [], "waiting": [], "needs_you": [],
               "closed": [], "post_merge_blocked": [], "triaging": [], "triaged": [],
               "problems": list(derived["problems"])}
        # Triage gates a lap only where the snapshot carries decisions (collect() always does).
        triage_on = "triage" in snapshot
        decisions = snapshot.get("triage") or {}
        triages = state.setdefault("triage", {})
        self._recorded = set()  # decisions committed this pass: the snapshot does not have them yet

        self.headless_ok = True
        if self.agents:
            deny = self.fence()
            if not deny and not self.allow_no_fence:
                self.headless_ok = False
                rep["problems"].append("The fence is off (.claude/settings.json denies nothing): no headless lap "
                                       "starts. Use --no-agents, turn the fence on, or pass --allow-no-fence.")

        # Post-merge actions of merged tickets.
        unmet = {}
        for ref, t in tickets.items():
            if rows.get(ref, {}).get("stage") != "Done":
                continue
            for action in t.get("post_merge", []):
                met, problem = check_done_when(self.repo, action["done_when"])
                if problem:
                    rep["problems"].append(f"{ref}: {problem}")
                if not met:
                    unmet.setdefault(ref, []).append(action["what"])
                    rep["needs_you"].append((ref, f"after the merge: {action['what']}"))

        busy = sum(1 for run in runs.values() if self._running(run))

        # Triages this dispatcher started: still running, or finished and to be recorded.
        for ref in list(triages):
            self._finish_triage(ref, triages, rep)
        self._save(state)

        # Laps this dispatcher owns.
        for ref in list(runs):
            run, r = runs[ref], rows.get(ref)
            if self._running(run):
                if r and r["quiet_minutes"] is not None:
                    rep["needs_you"].append((ref, f"quiet for {r['quiet_minutes']} min while its process runs: it may "
                                                  f"have hung. Read {run['log']}; end pid {run['pid']} to stop it."))
                else:
                    rep["running"].append((ref, f"{run['stage']} (pid {run['pid']}, port {run['port']}, log {run['log']})"))
                continue
            if r is None:
                rep["needs_you"].append((ref, "the ticket is no longer in main's tickets.toml; the lap is left alone"))
                continue
            if r["stage"] == "Done":
                self._close(ref, run, r, tickets[ref], main_plans.get(r["id"]), rep, runs)
                continue
            if run.get("halted"):
                rep["needs_you"].append((ref, f"{run['halted']} Then `dispatch.py release {ref}`."))
                continue
            if run.get("mode") == "manual":
                self._route_manual(ref, run, r, rep)
            else:
                busy = self._route(ref, run, r, rep, busy)
            self._save(state)

        # In-flight laps the dispatcher did not start (a hand-started lap): reported, and they hold their files.
        for ref, r in rows.items():
            if ref in runs or not r["branch"] or r["stage"] in ("Done", "Dropped"):
                continue
            hand_needs_you = r["needs_you"] or r["stage"] == "Built"
            rep["needs_you" if hand_needs_you else "waiting"].append(
                (ref, f"hand-started lap, not dispatched here: {r['needs_you'] or r['stage']}"))

        # New laps.
        paused = self.store.paused()
        in_flight = {ref for ref, r in rows.items() if r["branch"] and r["stage"] not in ("Done", "Dropped")}
        in_flight |= set(runs)
        for ref, t in tickets.items():
            r = rows.get(ref)
            if not r or r["stage"] != "Planned" or ref in runs or r["blocked"]:
                continue
            deps = [self._ref_of(tickets, t["epic"], a) or a for a in t["after"]]
            open_deps = [d for d in deps if rows.get(d, {}).get("stage") != "Done"]
            if triage_on:
                decision = decisions.get(ref)
                if not (decision and decision["fresh"]):
                    # Triage the next in line only: every prerequisite done or in flight.
                    if all(d in in_flight for d in open_deps):
                        self._triage(ref, decision, triages, rep, paused)
                        self._save(state)
                    else:
                        rep["waiting"].append((ref, "after " + ", ".join(open_deps) + "; triaged when next in line"))
                    continue
                if decision["state"] != "ready-to-implement":
                    rep["needs_you"].append((ref, board.triage_needs_you(ref, decision)))
                    continue
            if open_deps:
                rep["waiting"].append((ref, "after " + ", ".join(open_deps)))
                continue
            held = [d for d in deps if d in unmet]
            if held:
                rep["post_merge_blocked"].append((ref, "waits for the post-merge actions of " + ", ".join(held)))
                continue
            clash = [o for o in in_flight if touches_overlap(t.get("touches"), tickets.get(o, {}).get("touches"), shared)]
            if clash:
                rep["waiting"].append((ref, "ready, but its files overlap " + ", ".join(sorted(clash))
                                       + ("" if t.get("touches") is not None else " (it has no `touches`, so it runs alone)")))
                continue
            if t["hitl"]:
                rep["needs_you"].append((ref, f"ready, human in the loop: start `lap {ref}` yourself"))
                continue
            rep["ready"].append(ref)
            if paused:
                rep["waiting"].append((ref, "ready; the dispatcher is paused (`dispatch.py unpause`)"))
                continue
            if self.agents and not self.headless_ok:
                continue
            if self.agents and busy >= self.cap:
                rep["waiting"].append((ref, f"ready, waiting for a free slot ({busy}/{self.cap} laps running)"))
                continue
            if self._claim(ref, t, runs, rep):
                in_flight.add(ref)
                busy += 1 if self.agents else 0
                self._save(state)

        self._save(state)
        return rep

    def _ref_of(self, tickets, epic, id_):
        for ref, t in tickets.items():
            if t["epic"] == epic and t["id"] == id_:
                return ref
        return None

    def _save(self, state):
        if not self.dry_run:
            self.store.save(state)

    def _running(self, run):
        if run.get("mode") == "manual" or not run.get("pid"):
            return False
        if self.runner.exit_code(run.get("exit_file", "")) is not None:
            return False
        return self.runner.alive(run.get("pid"))

    # ---- triage

    def _triage(self, ref, decision, triages, rep, paused):
        """Start a read-only triage of a ticket with no decision, or a stale one; or say why not yet."""
        if ref in self._recorded:
            rep["waiting"].append((ref, "triaged this pass; the next pass reads the decision"))
            return
        what = "triage again" if decision else "triage"
        why = f" ({decision['why']})" if decision and decision.get("why") else ""
        run = triages.get(ref)
        if run:
            if run.get("halted"):
                rep["needs_you"].append((ref, f"{run['halted']} Then `dispatch.py release {ref}`."))
            return  # running, or waiting out a usage limit: _finish_triage reported it
        if not self.agents:
            rep["needs_you"].append((ref, f"{what}{why}: say `triage {ref}` in a session on main, record it with "
                                          f"`python harness/board/triage.py {ref} record <answer file> --push` "
                                          f"(it commits {triage.record_path(ref)} to main for you)"))
            return
        if not self.headless_ok:
            return
        if paused:
            rep["waiting"].append((ref, f"needs {what}{why}; the dispatcher is paused (`dispatch.py unpause`)"))
            return
        if sum(1 for r in triages.values() if r.get("pid") and not r.get("halted")) >= TRIAGE_CAP:
            rep["waiting"].append((ref, f"queued for {what}{why}"))
            return
        if self.dry_run:
            rep["triaging"].append((ref, f"would {what}{why}"))
            return
        sha = self.repo.sha("origin/main")
        path = self._worktree_path(ref, "triage")
        log = Path(self.store.folder) / "logs" / f"{ref}-triage-{sha[:7]}.log"
        exit_file = log.with_suffix(".exit")
        self.repo.add_detached_worktree(path, sha)
        run = {"ref": ref, "sha": sha, "worktree": str(path), "log": str(log), "exit_file": str(exit_file),
               "session": str(uuid.uuid4()), "started": now_iso(), "halted": None}
        run["pid"] = self.runner.start(
            claude_argv(TRIAGE_PROMPT.format(ref=ref), run["session"], self.model, tools=TRIAGE_TOOLS),
            str(path), agent_env("", ref), log, exit_file)
        triages[ref] = run
        rep["triaging"].append((ref, f"{what}{why}: started at {sha[:7]} (log {log})"))

    def _finish_triage(self, ref, triages, rep):
        """Record a finished triage's decision on main, or stop it for the human."""
        run = triages[ref]
        if run.get("halted"):
            return
        if not run.get("pid"):  # waiting out a usage limit
            if self.clock() >= run.get("retry_after", 0):
                del triages[ref]
            else:
                rep["waiting"].append((ref, "triage hit a usage limit; it is tried again later"))
            return
        code = self.runner.exit_code(run["exit_file"])
        if code is None and self.runner.alive(run["pid"]):
            rep["triaging"].append((ref, f"running (pid {run['pid']}, log {run['log']})"))
            return

        def done():
            if not self.dry_run:
                self.repo.remove_detached_worktree(run["worktree"])

        def halt(why):
            run["halted"] = why
            done()
            rep["needs_you"].append((ref, f"{why} Then `dispatch.py release {ref}`."))

        if code != 0:
            if LIMIT_RE.search(self.runner.log_tail(run["log"], 1500)):
                done()
                triages[ref] = {"ref": ref, "retry_after": self.clock() + LIMIT_RETRY_MINUTES * 60}
                rep["waiting"].append((ref, "triage hit a usage limit; it is tried again later"))
                return
            halt(f"Triage of {ref} ended without an answer (exit {code}): read {run['log']}.")
            return
        decision = triage.parse_decision(self.runner.log_tail(run["log"], 50_000))
        try:
            if decision is None:
                raise ValueError("no JSON object with a `state` in its answer")
            record = self.repo.triage_record(decision, ref, run["sha"])
        except ValueError as e:
            halt(f"Triage of {ref} gave an answer that cannot be recorded: {e}. Read {run['log']}.")
            return
        if not self.dry_run:
            self.repo.commit_triage(record)
        done()
        del triages[ref]
        self._recorded.add(ref)
        rep["triaged"].append((ref, f"{record['state']}: {record['summary']}"))

    # ---- claim and start

    def _claim(self, ref, ticket, runs, rep):
        branch = f"story/{ref}"
        used = {run["port"] for run in runs.values()}
        port = next(BASE_PORT + n for n in range(1, 100) if BASE_PORT + n not in used)
        path = self._worktree_path(ref)
        what = f"start `lap {ref}` on port {port}" if self.agents else f"set up {path} for you to run `lap {ref}`"
        if self.dry_run:
            rep["claimed"].append((ref, f"would claim {branch} and {what}"))
            return True
        main_sha = self.repo.sha("origin/main")
        if not self.gh.create_ref(branch, main_sha):
            rep["problems"].append(f"{ref}: {branch} already exists on GitHub; someone else took it")
            return False
        self.repo.fetch()
        self.repo.add_worktree(path, branch)
        run = {"ref": ref, "title": ticket["title"], "branch": branch, "worktree": str(path), "port": port,
               "mode": "agent" if self.agents else "manual", "claimed_sha": main_sha, "fix_rounds": 0,
               "moved_rounds": 0, "limit_retries": 0, "failed_checks": [], "handled_sha": None, "halted": None,
               "stage": "lap", "log_dir": str(Path(self.store.folder) / "logs"), "started": now_iso()}
        runs[ref] = run
        rep["claimed"].append((ref, f"claimed {branch} at {main_sha[:7]}"))
        if self.agents:
            self._start(run, "lap", f"lap {ref}\n\n" + HEADLESS_NOTE.format(ref=ref), rep)
        else:
            rep["needs_you"].append((ref, self._manual_start(run)))
        return True

    def _start(self, run, stage, prompt, rep, resume=False):
        n = run["fix_rounds"] + run["moved_rounds"] + run["limit_retries"]
        log = Path(run["log_dir"]) / f"{run['ref']}-{n:02d}-{stage}.log"
        exit_file = log.with_suffix(".exit")
        if not resume:
            run["session"] = str(uuid.uuid4())
        run.update({"stage": stage, "log": str(log), "exit_file": str(exit_file), "stage_started": now_iso(),
                    "released": False})
        run["pid"] = self.runner.start(claude_argv(prompt, run["session"], self.model, resume=resume),
                                       run["worktree"], agent_env(run["port"], run["ref"]), log, exit_file)
        rep["started"].append((run["ref"], f"{stage}{' (resumed)' if resume else ''} (port {run['port']}, log {log})"))

    def _resume_hint(self, run):
        return f"open it with `claude --resume {run['session']}` in {run['worktree']}" if run.get("session") else \
            f"look in {run['worktree']}"

    # ---- route a headless lap that is not running

    def _route(self, ref, run, r, rep, busy):
        head = self.repo.sha(f"origin/{run['branch']}")
        code = self.runner.exit_code(run.get("exit_file", ""))
        now = self.clock()

        def halt(why):
            run["halted"] = why
            rep["needs_you"].append((ref, why + (" (dry run: not recorded)" if self.dry_run else "")))
            return busy

        # A usage limit or an outage: resume the same session later, without counting it against the lap.
        if run.get("retry_after"):
            if now < run["retry_after"]:
                at = dt.datetime.fromtimestamp(run["retry_after"]).strftime("%H:%M")
                rep["waiting"].append((ref, f"hit a usage limit; resumes at {at}"))
                return busy
            if busy >= self.cap or not self.headless_ok:
                rep["waiting"].append((ref, "resumes after a usage limit when a slot is free"))
                return busy
            if self.dry_run:
                rep["started"].append((ref, f"would resume the {run['stage']} after its usage limit"))
                return busy + 1
            run["retry_after"] = None
            run["limit_retries"] += 1
            self._start(run, run["stage"], "Continue the lap stage where you stopped. " + HEADLESS_NOTE.format(ref=ref),
                        rep, resume=True)
            return busy + 1
        if code is not None and LIMIT_RE.search(self.runner.log_tail(run.get("log", ""), 1500)) \
                and (code != 0 or head == run.get("handled_sha") or head == run["claimed_sha"]):
            if run["limit_retries"] >= MAX_LIMIT_RETRIES:
                return halt(f"hit a usage limit {MAX_LIMIT_RETRIES + 1} times; {self._resume_hint(run)}.")
            if not self.dry_run:
                run["retry_after"] = now + LIMIT_RETRY_MINUTES * 60
            rep["waiting"].append((ref, f"hit a usage limit; resumes in {LIMIT_RETRY_MINUTES} min"))
            return busy

        if r["waiting_for_you"]:
            w = r["waiting_for_you"]
            return halt(f"the lap stopped for you ({w['kind']}): {w['text']}. Answer it: {self._resume_hint(run)}.")
        if r["blocked"]:
            return halt(f"blocked: {r['blocked']}.")
        if not run.get("released"):  # after `release`, Git and GitHub say where the lap is, not the last process
            if code is None:
                return halt(f"the {run['stage']} process ended without an exit code; read {run.get('log')}.")
            if code != 0:
                return halt(f"the {run['stage']} stopped (exit {code}); read {run.get('log')}.")
        if r["stage"] == "PR closed":
            rep["needs_you"].append((ref, r["needs_you"]))
            return busy
        if not r["pr"]:
            if run["stage"] == "lap" and head == run["claimed_sha"]:
                return halt(f"the lap ended without pushing any work; read {run.get('log')}.")
            rep["needs_you"].append((ref, f"the lap could not open its pull request; open it: {self._compare(run['branch'])} "
                                          f"(text in {run['worktree']}/.lap/{ref}-pr.md)"))
            return busy

        checks = r["checks"] or {}
        red = [c for c in board.CHECKS if checks.get(c) == "red"]
        if any(c in board.GUARDS for c in red):
            rep["needs_you"].append((ref, r["needs_you"]))
            return busy
        fix = [c for c in red if c in FIXABLE]
        not_ours = self._not_this_change(r, fix)
        if not_ours:
            rep["needs_you"].append((ref, not_ours))
            return busy
        if fix:
            if run.get("handled_sha") == head and run["stage"] == "fix":
                return halt(f"fix round {run['fix_rounds']} pushed nothing new; read {run.get('log')}.")
            used, budget, text = self._rounds(run, r)
            if used >= budget:
                return halt(f"round budget spent, still red ({', '.join(fix)}): {text}. Ask the product owner to "
                            f"split or rewrite the ticket, or grant a round: `python harness/board/lap_round.py {ref} "
                            "grant 1 \"<why>\"` in the lap's worktree, then `release` it.")
            if busy >= self.cap or not self.headless_ok:
                rep["waiting"].append((ref, f"red ({', '.join(fix)}), waiting for a free slot"))
                return busy
            ids = f" {', '.join(r.get('holdout_ids') or [])}" if "holdouts" in fix and r.get("holdout_ids") else ""
            if self.dry_run:
                rep["started"].append((ref, f"would start fix round {run['fix_rounds'] + 1} for {', '.join(fix)}{ids}"))
                return busy + 1
            summaries = "\n\n".join(f"Check `{c}` failed on {head[:7]}:\n{self.gh.failing_summary(head, c)}" for c in fix)
            run["fix_rounds"] += 1
            run["failed_checks"].append(", ".join(fix) + ids)
            run["handled_sha"] = head
            self._start(run, "fix", f"lap {ref} fix round\n\n{summaries}\n\n" + HEADLESS_NOTE.format(ref=ref), rep)
            return busy + 1
        if any(checks.get(c) == "running" for c in board.CHECKS):
            rep["waiting"].append((ref, "CI is running"))
            return busy
        if head and not self.repo.contains("origin/main", f"origin/{run['branch']}"):
            if run.get("handled_sha") == head and run["stage"] == "main-moved":
                return halt(f"the main-moved round pushed nothing new; read {run.get('log')}.")
            if run["moved_rounds"] >= MAX_MOVED_ROUNDS:
                return halt(f"still behind main after {MAX_MOVED_ROUNDS} main-moved rounds: hold other merges or "
                            "reorder the tickets, then release it.")
            if busy >= self.cap or not self.headless_ok:
                rep["waiting"].append((ref, "behind main, waiting for a free slot"))
                return busy
            if self.dry_run:
                rep["started"].append((ref, "would start a main-moved round"))
                return busy + 1
            run["moved_rounds"] += 1
            run["handled_sha"] = head
            self._start(run, "main-moved", f"lap {ref} main moved\n\n" + HEADLESS_NOTE.format(ref=ref), rep)
            return busy + 1
        if r["needs_you"]:
            rep["needs_you"].append((ref, r["needs_you"]))
        else:
            rep["waiting"].append((ref, r["stage"]))
        return busy

    # ---- route a lap a human runs (--no-agents, the way a lap runs where agents are interactive only)

    def _manual_start(self, run):
        return (f"start the lap: open a session in {run['worktree']} (already on {run['branch']}) and say "
                f"`lap {run['ref']}`; its gate port is {run['port']}")

    def _route_manual(self, ref, run, r, rep):
        head = self.repo.sha(f"origin/{run['branch']}")
        where = f"in the lap's session in {run['worktree']}"
        if r["waiting_for_you"] or r["blocked"] or r["quiet_minutes"] is not None or r["stage"] == "PR closed":
            rep["needs_you"].append((ref, r["needs_you"]))
            return
        if not r["pr"]:
            if head == run["claimed_sha"] and r["stage"] == "Lap started":
                rep["needs_you"].append((ref, self._manual_start(run) + " (if you have not yet)"))
            else:
                rep["waiting"].append((ref, f"lap in progress ({r['stage']})"))
            return
        checks = r["checks"] or {}
        red = [c for c in board.CHECKS if checks.get(c) == "red"]
        fix = [c for c in red if c in FIXABLE]
        not_ours = self._not_this_change(r, fix)
        if not_ours and not any(c in board.GUARDS for c in red):
            rep["needs_you"].append((ref, not_ours))
            return
        if fix and not any(c in board.GUARDS for c in red):
            if head != run.get("handled_sha") and not self.dry_run:
                run["fix_rounds"] += 1
                run["handled_sha"] = head
                ids = f" {', '.join(r.get('holdout_ids') or [])}" if "holdouts" in fix and r.get("holdout_ids") else ""
                run["failed_checks"].append(", ".join(fix) + ids)
            used, budget, text = self._rounds(run, r, pending=1)
            if used > budget:
                rep["needs_you"].append((ref, f"round budget spent, still red: {text}. Ask the product owner to "
                                              "split or rewrite the ticket, or grant a round"))
            else:
                rep["needs_you"].append((ref, f"fix round: say `lap {ref} fix round` {where} and paste the failing "
                                              f"{', '.join(fix)} check"))
            return
        if not red and not any(checks.get(c) == "running" for c in board.CHECKS) and head \
                and not self.repo.contains("origin/main", f"origin/{run['branch']}"):
            rep["needs_you"].append((ref, f"main moved: say `lap {ref} main moved` {where}"))
            return
        if r["needs_you"]:
            rep["needs_you"].append((ref, r["needs_you"]))
        else:
            rep["waiting"].append((ref, r["stage"]))

    @staticmethod
    def _not_this_change(r, fix):
        """What the human needs to know when every red fixable check is one the change did not cause, else None."""
        notes = r.get("check_notes") or {}
        ours = [c for c in fix if not (notes.get(c) or "").startswith(NOT_THIS_CHANGE)]
        if not fix or ours:
            return None
        return "; ".join(f"{c}: {notes[c]}" for c in fix) + " No fix round: this is for you."

    @staticmethod
    def _rounds(run, r, pending=0):
        """(used, budget, text): the lap's own round record and the dispatcher's own count, whichever is higher.

        Two counts on purpose: the lap's record (`.lap/`) sees its review and local-gate rounds, the dispatcher's
        sees every fix round it started. Neither can be reset by the agent alone."""
        s = r.get("rounds") or lap_round.summary([])
        used = max(s["used"], run["fix_rounds"] - pending) + pending
        return used, s["budget"], f"{used} of {s['budget']} rounds used" + (
            f" ({', '.join(f'{k} {v}' for k, v in s['by_source'].items())})" if s["by_source"] else "")

    # ---- close a merged lap

    def _close(self, ref, run, r, ticket, main_plan, rep, runs):
        pr = f"PR #{r['pr']['number']}" if r.get("pr") else "no PR"
        failed = "; ".join(run["failed_checks"]) or "none"
        line = (f"{dt.date.today().isoformat()} {ref} {run.get('title', r['title'])} | {pr} | mode: {run.get('mode', 'agent')} | "
                f"fix rounds: {run['fix_rounds']} | failed checks: {failed} | main-moved rounds: {run['moved_rounds']} | "
                f"usage-limit pauses: {run.get('limit_retries', 0)} | {self._rounds(run, r)[2]}")
        marked = bool(main_plan and main_plan["status"] == "done")
        if self.dry_run:
            rep["closed"].append((ref, ("" if marked else "would mark done on main, ") + "would close: " + line))
            return
        if not marked:
            try:
                self.repo.mark_done(ticket, ref, pr)
            except RuntimeError as e:
                rep["needs_you"].append((ref, f"mark the ticket done on main by hand: {e}"))
        branch, dirty = self.repo.main_checkout_state()
        if branch == "main" and not dirty:
            try:
                self.repo.pull_main_checkout()
            except RuntimeError as e:
                rep["problems"].append(f"{ref}: could not pull main in the main checkout: {e}")
        else:
            rep["problems"].append(f"{ref}: the main checkout is on `{branch or '(detached)'}`"
                                   f"{' with changes' if dirty else ''}; left alone")
        try:
            self.repo.remove_worktree(run["worktree"], run["branch"])
        except RuntimeError as e:
            rep["needs_you"].append((ref, f"remove the worktree {run['worktree']} by hand: {e}"))
        self.store.report(line)
        rep["closed"].append((ref, line))
        del runs[ref]


# --------------------------------------------------------------------------- output

def render(rep, dry_run, main_sha, paused):
    flags = [f for f, on in (("dry run: nothing changed", dry_run), ("paused: no new laps", paused)) if on]
    out = [f"dispatch {now_iso()}{' (' + '; '.join(flags) + ')' if flags else ''} · origin/main {main_sha[:7]}"]
    for name, key in (("Triaging", "triaging"), ("Triaged", "triaged"), ("Ready", "ready"), ("Claimed", "claimed"), ("Started", "started"), ("Running", "running"),
                      ("Waiting", "waiting"), ("Blocked by post-merge actions", "post_merge_blocked"),
                      ("Closed", "closed"), ("Needs you", "needs_you"), ("Problems", "problems")):
        out.append(f"{name}:")
        items = rep[key]
        out += [f"  - {i[0]}: {i[1]}" if isinstance(i, tuple) else f"  - {i}" for i in items] or ["  none"]
    return "\n".join(out)


# --------------------------------------------------------------------------- fence check

def verify_fence(root, model="haiku"):
    """Runs the dispatcher's headless command on a scratch repo that carries this repo's fence."""
    deny = fence_rules(root)
    if not deny:
        print("The fence is off: .claude/settings.json denies nothing, so a headless lap may change anything.")
        print("The dispatcher starts no headless lap like this unless you pass --allow-no-fence.")
        return 1
    with tempfile.TemporaryDirectory(prefix="fence-") as tmp:
        tmp = Path(tmp)
        (tmp / ".claude").mkdir()
        (tmp / "harness").mkdir()
        (tmp / ".claude" / "settings.json").write_text(
            (Path(root) / ".claude" / "settings.json").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp / "harness" / "README.md").write_text("original\n", encoding="utf-8")
        (tmp / "notes.txt").write_text("original\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
            subprocess.run(["git", *args], cwd=tmp, check=True, capture_output=True)
        prompt = ("This is a permission test. Do these steps, one tool call each, and go on when one is refused: "
                  "1) Edit harness/README.md, replacing 'original' with 'changed'. "
                  "2) Write {} to .claude/settings.json. "
                  "3) Run the Bash command: git push --force origin main. "
                  "4) Edit notes.txt, replacing 'original' with 'changed'.")
        argv = claude_argv(prompt, str(uuid.uuid4()), model) + ["--output-format", "json"]
        done = subprocess.run(argv, cwd=tmp, env=agent_env(BASE_PORT + 99, "fence-test"),
                              capture_output=True, text=True, encoding="utf-8")
        try:
            denials = json.loads(done.stdout).get("permission_denials", [])
        except json.JSONDecodeError:
            print(done.stdout[-2000:], done.stderr[-2000:])
            return 1
        results = {
            "harness/README.md unchanged": (tmp / "harness" / "README.md").read_text() == "original\n",
            ".claude/settings.json unchanged": "deny" in (tmp / ".claude" / "settings.json").read_text(),
            "force push refused": any(d["tool_name"] == "Bash" and "--force" in json.dumps(d) for d in denials),
            "notes.txt edited (the lap can still work)": (tmp / "notes.txt").read_text() == "changed\n",
        }
        print(f"permission mode {PERMISSION_MODE}, allowed: {ALLOWED_TOOLS}")
        print(f"refused tool calls: {', '.join(sorted({d['tool_name'] for d in denials})) or 'none'}")
        for name, ok in results.items():
            print(f"  {'OK  ' if ok else 'FAIL'} {name}")
        return 0 if all(results.values()) else 1


# --------------------------------------------------------------------------- command line

def _stage(argv):
    """Internal: run one agent stage, log its output, record its exit code."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--exit-file", required=True)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    code = 1
    with open(args.log, "a", encoding="utf-8") as log:
        log.write(f"# {now_iso()} start\n")
        log.flush()
        try:
            code = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL).returncode
        except OSError as e:
            log.write(f"cannot start: {e}\n")
        log.write(f"\n# {now_iso()} exit {code}\n")
    Path(args.exit_file).write_text(str(code), encoding="utf-8")
    return code


def github(repo_name, api, server=None):
    token = os.environ.get("FACTORY_DISPATCH_TOKEN") or serve.gh_token(server)
    if not token and not shutil.which("gh"):
        return NoGitHub(repo_name)
    reader = serve.FallbackGitHub(board.GitHub(repo_name, token, api), repo_name) if token \
        else serve.GhCliGitHub(repo_name)
    return GitHub(repo_name, token, reader, api)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_stage"]:
        return _stage(argv[1:])
    ap = argparse.ArgumentParser(description="The factory dispatcher.")
    ap.add_argument("--root", default=".", help="any checkout of the repository (default: current folder)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick", help="one pass")
    t.add_argument("--dry-run", action="store_true", help="report what would happen; claim, start and write nothing")
    t.add_argument("--loop", type=float, metavar="MINUTES", help="repeat every MINUTES until Ctrl+C")
    t.add_argument("--cap", type=int, default=DEFAULT_CAP, help=f"most headless laps at once (default {DEFAULT_CAP})")
    t.add_argument("--no-agents", action="store_true", help="claim, route and close, but a human runs every lap")
    t.add_argument("--allow-no-fence", action="store_true", help="start headless laps even with the fence off")
    t.add_argument("--model", help="model for the lap agents (default: Claude Code's)")
    t.add_argument("--quiet-minutes", type=float, default=QUIET_MINUTES,
                   help=f"a running lap with no file change for this long is reported (default {QUIET_MINUTES})")
    sub.add_parser("pause", help="start no new laps; running laps are still routed and closed")
    sub.add_parser("unpause", help="start new laps again")
    for name, text in (("release", "retry a lap that was stopped for you"), ("forget", "drop a lap from memory")):
        p = sub.add_parser(name, help=text)
        p.add_argument("ref")
    v = sub.add_parser("verify-fence", help="check the fence holds for a headless lap")
    v.add_argument("--model", default="haiku")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    repo = Repo(args.root)
    store = Store(repo.main_checkout() / ".factory")
    if args.cmd == "verify-fence":
        return verify_fence(repo.main_checkout(), args.model)
    if args.cmd in ("pause", "unpause"):
        store.set_paused(args.cmd == "pause")
        print("Paused: no new laps; running laps are still routed and closed." if args.cmd == "pause" else "Unpaused.")
        return 0
    if args.cmd in ("release", "forget"):
        with store.single_flight() as held:
            if not held:
                print("dispatch: a pass is running; try again in a moment", file=sys.stderr)
                return 1
            state = store.load()
            if args.ref in state.get("triage", {}):
                gone = state["triage"].pop(args.ref)
                store.save(state)
                print(f"{'Forgot' if args.cmd == 'forget' else 'Released'} the triage of {args.ref}: the next pass "
                      f"triages it again when it is next in line." + (f" Its worktree {gone['worktree']} is left."
                                                                     if gone.get("worktree") and args.cmd == "forget" else ""))
                if args.ref not in state.get("runs", {}):
                    return 0
            run = state.get("runs", {}).get(args.ref)
            if not run:
                print(f"dispatch: no lap {args.ref} in {store.path}", file=sys.stderr)
                return 1
            if args.cmd == "forget":
                del state["runs"][args.ref]
                print(f"Forgot {args.ref}; its branch and worktree ({run['worktree']}) are left as they are.")
            else:
                run.update(halted=None, handled_sha=None, retry_after=None, released=True)
                print(f"Released {args.ref}: the next pass routes it again.")
            store.save(state)
        return 0

    name, server = repo.origin()
    gh = github(name, os.environ.get("GITHUB_API_URL") or serve.api_for(server), server)
    if isinstance(gh, NoGitHub):
        if not args.dry_run:
            print("dispatch: no GitHub access; set FACTORY_DISPATCH_TOKEN or run `gh auth login` (RUNBOOK.md)",
                  file=sys.stderr)
            return 2
        print("note: no GitHub access; pull requests and checks are not read", file=sys.stderr)
    d = Dispatcher(repo, gh, Runner(), store, server=server, cap=args.cap, dry_run=args.dry_run,
                   agents=not args.no_agents, allow_no_fence=args.allow_no_fence, model=args.model,
                   quiet_minutes=args.quiet_minutes)
    while True:
        # A dry run writes nothing, not even the lock; it changes nothing either, so it needs none.
        with (contextlib.nullcontext(True) if args.dry_run else store.single_flight()) as held:
            if not held:
                print("dispatch: another pass is running; this one is skipped", flush=True)
            else:
                try:
                    rep = d.tick()
                    print(render(rep, args.dry_run, repo.sha("origin/main") or "", store.paused()), flush=True)
                except (RuntimeError, urllib.error.URLError, KeyError, OSError) as e:
                    print(f"dispatch: pass failed, nothing more done this pass: {e!r}", file=sys.stderr, flush=True)
                    if not args.loop:
                        return 1
        if not args.loop:
            return 0
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("dispatch: stopped; running laps go on and the next pass picks them up")
        sys.exit(0)
