#!/usr/bin/env python3
"""The factory judge, for GitHub hosts where Actions is not allowed. Human-owned.

Part of the judge. Standard library only (Python 3.11+).

  python harness/judge/judge.py [--root .] [--once] [--pr N] [--interval 120] [--dry-run]
                                [--no-gates] [--port 8190] [--gates-timeout 30]

On demand, when a lap has opened its pull request (no need to keep anything running):

  python harness/judge/judge.py --once --pr 12

judges that pull request (both guards and the gates), prints its three results and exits 0 only
when all three are green. `--once` without `--pr` judges everything open, `main` included, and
exits. Without `--once` it keeps running, one pass every `--interval` seconds.

Each pass reads the open pull requests and posts the commit statuses the workflows would post
as checks, so the board, the dispatcher and branch protection see them as they see checks:

- `protected-paths` and `scope-guard` (as `judge-guards.yml`): judged by `guards.py` from the
  changed file names and the labels, for every open pull request, every pass.
- `gates` (as `gates.yml`): `harness/run-gates.sh` on the pull request merged with `main`, in a
  worktree of this clone, with `harness/` restored from `main` so a pull request cannot change
  the gate that judges it. Then on `main` itself, as on a push to `main`. One gate run per pass,
  oldest pull request first; each commit is judged once. A failure's last log lines go into one
  comment on the pull request, edited in place, which the dispatcher reads for a fix round.
  A pull request that conflicts with `main` gets no `gates` status: it needs a "main moved" round.

A status is posted only when it differs from the judge's verdict, so a status someone else
posted is overwritten on the next pass. Verdicts and logs are kept in `.factory/judge/`.

The gate runs pull request code on this machine. It runs with no GitHub token in its
environment; run the judge in its own clone, on a machine where nothing else secret is reachable.

GitHub: FACTORY_JUDGE_TOKEN, else GITHUB_TOKEN, else `gh auth token` for origin's host. The token
needs Pull requests read and write (the comment) and Commit statuses write. Never give it to a lap.
"""
import argparse
import datetime
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "board"))
import guards  # noqa: E402
import board  # noqa: E402  (the paged GitHub reader)
import serve  # noqa: E402  (origin, host, API root, token, certificate fallback)

USER_AGENT = "factory-judge"
GATES = "gates"
MARKER = "<!-- factory-judge:gates -->"
DEFAULT_PORT = 8190  # 8080 is the human's app, 8081 a hand-started lap, 8090+ dispatched laps
DEFAULT_TIMEOUT_MINUTES = 30  # as gates.yml
LOG_TAIL_LINES = 80
SECRET_VARS = ("FACTORY_JUDGE_TOKEN", "FACTORY_DISPATCH_TOKEN", "GITHUB_TOKEN", "GH_TOKEN",
               "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
LAP_SKILLS = (".claude/skills/lap/SKILL.md", ".kiro/skills/lap/SKILL.md")
IDENTITY = ["-c", "user.name=factory-judge", "-c", "user.email=factory-judge@localhost"]


class GitHub:
    """Reads through the board's client; writes commit statuses and the judge's one comment."""

    def __init__(self, repo, server, token):
        self.repo, self.token, self.api = repo, token, serve.api_for(server)
        self.reader = serve.FallbackGitHub(board.GitHub(repo, token, self.api), repo) if token \
            else serve.GhCliGitHub(repo)

    def get(self, path, key=None):
        return self.reader.get(path, key)

    def _send(self, method, path, body):
        if self.token and not getattr(self.reader, "via_gh", False):
            req = urllib.request.Request(f"{self.api}/repos/{self.repo}{path}", data=json.dumps(body).encode(),
                                         method=method, headers={
                                             "Authorization": f"Bearer {self.token}",
                                             "Accept": "application/vnd.github+json",
                                             "X-GitHub-Api-Version": "2022-11-28",
                                             "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30):
                return
        done = subprocess.run(["gh", "api", "-X", method, f"repos/{self.repo}{path}", "--input", "-"],
                              input=json.dumps(body), capture_output=True, text=True, encoding="utf-8", timeout=60)
        if done.returncode != 0:
            raise RuntimeError(f"{method} {path}: {done.stderr.strip()}")

    def post_status(self, sha, context, state, description):
        self._send("POST", f"/statuses/{sha}", {"state": state, "context": context, "description": description})

    def post_comment(self, number, body):
        self._send("POST", f"/issues/{number}/comments", {"body": body})

    def edit_comment(self, comment_id, body):
        self._send("PATCH", f"/issues/comments/{comment_id}", {"body": body})


def ignore_folder(folder):
    """`.factory/` is ignored by Git through its own `.gitignore`, so a lap's tree stays clean."""
    top = Path(folder).parent
    top.mkdir(parents=True, exist_ok=True)
    ignore = top / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")


class Conflict(Exception):
    """The pull request does not merge cleanly into `main`."""


class Workspace:
    """Git and the gate run, in worktrees of the judge's clone under `.factory/judge/work/`."""

    def __init__(self, root, folder):
        self.root, self.folder = Path(root), Path(folder)

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(["git", "-C", str(cwd or self.root), *args], capture_output=True, text=True,
                              encoding="utf-8", check=check)

    def fetch(self):
        """Fetch origin; return the `main` commit."""
        self.git("fetch", "--quiet", "--prune", "origin")
        return self.git("rev-parse", "origin/main").stdout.strip()

    def fetch_pull(self, number):
        """The pull request's head, through GitHub's own ref (works for forks, too)."""
        self.git("fetch", "--quiet", "origin", f"+refs/pull/{number}/head:refs/factory-judge/pull/{number}")
        return self.git("rev-parse", f"refs/factory-judge/pull/{number}").stdout.strip()

    def prepare(self, main, head=None):
        """A worktree of `main`, merged with `head` when given, with `harness/` from `main`."""
        path = self.folder / "work" / (head or main)[:12]
        ignore_folder(self.folder)
        self.cleanup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.git("worktree", "add", "--quiet", "--detach", str(path), main)
        if head:
            merged = self.git(*IDENTITY, "merge", "--quiet", "--no-edit", "--no-ff", head, cwd=path, check=False)
            if merged.returncode != 0:
                self.cleanup(path)
                raise Conflict(merged.stdout.strip() or merged.stderr.strip())
            self.git("rm", "-r", "-q", "-f", "--ignore-unmatch", "harness", cwd=path)
            self.git("checkout", main, "--", "harness", cwd=path)
        return path

    def run(self, path, candidate, port, log, timeout):
        """Run the gates; (exit code or None on timeout, seconds). Output goes to `log`."""
        log.parent.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k not in SECRET_VARS}
        env.update({"PORT": str(port), "FACTORY_RUNTIME_CANDIDATE": candidate})
        start = time.monotonic()
        with open(log, "w", encoding="utf-8") as out:
            skills = [Path(path) / s for s in LAP_SKILLS]  # as gates.yml: the lap skill is the same for every agent
            if not all(s.is_file() for s in skills) or len({s.read_bytes() for s in skills}) != 1:
                out.write(f"GATE FAIL: {LAP_SKILLS[1]} must be a copy of {LAP_SKILLS[0]}\n")
                return 1, time.monotonic() - start
            out.flush()
            group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
                else {"start_new_session": True}
            proc = subprocess.Popen(["bash", "harness/run-gates.sh"], cwd=path, env=env, stdout=out,
                                    stderr=subprocess.STDOUT, **group)
            try:
                return proc.wait(timeout=timeout), time.monotonic() - start
            except subprocess.TimeoutExpired:
                self._kill(proc)
                out.write(f"\nGATE STOPPED: did not finish in {timeout // 60} minutes.\n")
                return None, time.monotonic() - start

    @staticmethod
    def _kill(proc):
        """The gate's whole process tree, including the app it started."""
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait()

    def cleanup(self, path):
        if Path(path).exists():
            self.git("worktree", "remove", "--force", str(path), check=False)
            shutil.rmtree(path, ignore_errors=True)
        self.git("worktree", "prune", check=False)


class Verdicts:
    """The judge's own `gates` verdicts per commit, in `.factory/judge/verdicts.json`."""

    KEEP = 500

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.data = {}
        if self.path and self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                self.data = {}

    def get(self, sha):
        return self.data.get(sha)

    def put(self, sha, verdict):
        self.data[sha] = verdict
        if len(self.data) > self.KEEP:  # oldest first, as inserted
            for old in list(self.data)[: len(self.data) - self.KEEP]:
                del self.data[old]
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            ignore_folder(self.path.parent)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


def tail(path, lines=LOG_TAIL_LINES, limit=60000):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no log)"
    return "\n".join(text.splitlines()[-lines:])[-limit:]


class Judge:
    def __init__(self, gh, ws=None, verdicts=None, dry_run=False, out=print, port=DEFAULT_PORT,
                 timeout=DEFAULT_TIMEOUT_MINUTES * 60, only=None):
        self.gh, self.ws, self.dry_run, self.out, self.only = gh, ws, dry_run, out, only
        self.last_ran, self.results = None, {}
        self.verdicts = verdicts if verdicts is not None else Verdicts()
        self.port, self.timeout = port, timeout

    # -- statuses -------------------------------------------------------------------------

    def _post(self, sha, context, state, text, current, label=""):
        now = current.get(context)
        if now and now.get("state") == state and (now.get("description") or "") == text:
            return False
        if not self.dry_run:
            self.gh.post_status(sha, context, state, text)
        current[context] = {"context": context, "state": state, "description": text}
        self.out(f"{label}{sha[:7]} {context}: {'would post' if self.dry_run else 'posted'} {state} ({text})")
        return True

    def statuses(self, sha):
        return {s["context"]: s for s in self.gh.get(f"/commits/{sha}/status").get("statuses", [])}

    def judge_pull(self, pr, template, current=None):
        """Post this pull request's guard statuses where they changed. Returns what was posted."""
        sha = pr["head"]["sha"]
        labels = [label["name"] for label in pr.get("labels", [])]
        files = self.gh.get(f"/pulls/{pr['number']}/files")
        current = self.statuses(sha) if current is None else current
        posted = []
        for check in guards.CHECKS:
            passed, hits, message = guards.judge(check, files, labels, template)
            state = "success" if passed else "failure"
            if self._post(sha, check, state, guards.description(passed, hits, message), current, f"#{pr['number']} "):
                posted.append((pr["number"], check, state))
        return posted

    # -- gates ----------------------------------------------------------------------------

    def _enforce(self, sha, current, label):
        """Keep the posted `gates` status equal to the judge's verdict. False when there is none yet."""
        v = self.verdicts.get(sha)
        if not v or "state" not in v:
            return False
        self._post(sha, GATES, v["state"], v["description"], current, label)
        return True

    def gates_pass(self, pulls, currents):
        """At most one gate run: the oldest pull request with no verdict, else `main`."""
        main = self.ws.fetch()
        todo = []
        for pr in sorted(pulls, key=lambda p: p["number"]):
            sha = pr["head"]["sha"]
            if self._enforce(sha, currents[sha], f"#{pr['number']} "):
                continue
            v = self.verdicts.get(sha) or {}
            if v.get("conflict_with") == main:
                continue  # waits for a "main moved" round or for main to move
            todo.append(pr)
        if todo:
            return self.run_gates(todo[0], main, currents[todo[0]["head"]["sha"]])
        if self.only is not None:  # judging one pull request: main is not its business
            return None
        main_current = self.statuses(main)
        if not self._enforce(main, main_current, "main "):
            return self.run_gates(None, main, main_current)
        return None

    def run_gates(self, pr, main, current=None):
        label = f"#{pr['number']} " if pr else "main "
        if self.dry_run:
            self.out(f"{label}would run gates{' on the merge with main ' + main[:7] if pr else ' on ' + main[:7]}")
            return (pr["number"] if pr else "main", "dry-run")
        sha = self.ws.fetch_pull(pr["number"]) if pr else main
        if pr and sha != pr["head"]["sha"]:
            self.out(f"{label}moved while judging ({sha[:7]}); judged on a later pass")
            return None
        current = self.statuses(sha) if current is None else current
        try:
            path = self.ws.prepare(main, sha if pr else None)
        except Conflict:
            self.verdicts.put(sha, {"conflict_with": main, "pull": pr["number"]})
            self.out(f"{label}{sha[:7]} conflicts with main {main[:7]}: no gates status until it is merged with main")
            return (pr["number"], "conflict")
        where = f"merge with main {main[:7]}" if pr else f"main {main[:7]}"
        self._post(sha, GATES, "pending", f"Running on the {where} (factory judge).", current, label)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log = self.ws.folder / "logs" / f"{sha[:12]}-{stamp}-gates.log"
        try:
            code, seconds = self.ws.run(path, f"{sha}-judge-{stamp}", self.port, log, self.timeout)
        finally:
            self.ws.cleanup(path)
        minutes = max(1, round(seconds / 60))
        if code == 0:
            state, text = "success", f"Passed on the {where} in {minutes} min (factory judge)."
        elif code is None:
            state, text = "failure", f"Stopped after {self.timeout // 60} min on the {where} (factory judge)."
        else:
            state, text = "failure", f"Failed on the {where} (factory judge); see its comment."
        self.verdicts.put(sha, {"state": state, "description": text, "main": main, "log": str(log),
                                "pull": pr["number"] if pr else None})
        self._post(sha, GATES, state, text, current, label)
        if pr:
            self.comment(pr["number"], sha, main, state, log)
        return (pr["number"] if pr else "main", state)

    def comment(self, number, sha, main, state, log):
        """One comment per pull request, edited in place: the failing tail, or that the gates now pass."""
        mine = [c for c in self.gh.get(f"/issues/{number}/comments") if MARKER in (c.get("body") or "")]
        if state == "success":
            if not mine:
                return
            body = (f"{MARKER}\n<!-- sha:{sha} -->\n**gates** passed on `{sha[:7]}` merged with main "
                    f"`{main[:7]}` (factory judge).")
        else:
            body = (f"{MARKER}\n<!-- sha:{sha} -->\n**gates** failed on `{sha[:7]}` merged with main `{main[:7]}` "
                    f"(factory judge). Last lines of the log:\n\n```\n{tail(log)}\n```")
        if mine:
            self.gh.edit_comment(mine[-1]["id"], body)
        else:
            self.gh.post_comment(number, body)

    # -- one pass -------------------------------------------------------------------------

    def run_pass(self):
        template = bool(self.gh.get("").get("is_template"))
        posted, currents = [], {}
        pulls = self.gh.get("/pulls?state=open")
        if self.only is not None:
            pulls = [pr for pr in pulls if pr["number"] == self.only]
            if not pulls:
                self.out(f"#{self.only} is not an open pull request")
        judged = []
        for pr in pulls:
            try:
                currents[pr["head"]["sha"]] = self.statuses(pr["head"]["sha"])
                posted += self.judge_pull(pr, template, currents[pr["head"]["sha"]])
                judged.append(pr)
            except (RuntimeError, urllib.error.URLError) as e:  # one bad pull request does not stop the rest
                self.out(f"#{pr['number']}: not judged this pass: {e}")
        ran = None
        if self.ws:
            try:
                ran = self.gates_pass(judged, currents)
            except (RuntimeError, urllib.error.URLError, subprocess.CalledProcessError) as e:
                self.out(f"gates: not run this pass: {getattr(e, 'stderr', '') or e}")
        self.last_ran = ran
        self.results = {pr["number"]: {c: (currents[pr["head"]["sha"]].get(c) or {}).get("state", "missing")
                                       for c in (GATES, *guards.CHECKS)} for pr in judged}
        self.out(f"pass done: {len(pulls)} open pull request(s), {len(posted)} guard status(es) "
                 f"{'to post' if self.dry_run else 'posted'}, gates: {ran[1] if ran else 'nothing to run'}")
        return posted

    def drain(self, limit=50):
        """Passes until no gate is left to run (one pass in a dry run)."""
        for _ in range(limit):
            self.run_pass()
            if self.dry_run or self.last_ran is None:
                return

    def verdict(self, number):
        """For `--pr`: one line with the three results, and whether the pull request may merge."""
        results = self.results.get(number)
        if not results:
            return False, f"#{number}: not judged"
        if not self.ws:
            results = {c: s for c, s in results.items() if c != GATES}
        ok = all(s == "success" for s in results.values())
        text = ", ".join(f"{c} {s}" for c, s in results.items())
        return ok, f"#{number}: {text}. {'Ready for your review and merge.' if ok else 'Not ready to merge.'}"


def origin(root):
    url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                         capture_output=True, text=True, check=True).stdout.strip()
    repo, server = serve.repo_from_url(url), serve.server_from_url(url)
    if not repo:
        raise SystemExit(f"cannot read owner/name from origin {url}")
    return repo, os.environ.get("GITHUB_SERVER_URL", server)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", default=".", help="the judge's own clone of the project")
    p.add_argument("--once", action="store_true", help="judge what is waiting, then exit")
    p.add_argument("--pr", type=int, help="judge only this pull request (with --once: exit 0 only when it is green)")
    p.add_argument("--interval", type=int, default=120, help="seconds between passes (default 120)")
    p.add_argument("--dry-run", action="store_true", help="print what would be posted or run; do neither")
    p.add_argument("--no-gates", action="store_true", help="the two guards only (a machine without Java or Node)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"the gate's app port (default {DEFAULT_PORT})")
    p.add_argument("--gates-timeout", type=int, default=DEFAULT_TIMEOUT_MINUTES, help="minutes (default 30)")
    a = p.parse_args(argv)
    root = Path(a.root).resolve()
    repo, server = origin(root)
    token = os.environ.get("FACTORY_JUDGE_TOKEN") or serve.gh_token(server)
    folder = root / ".factory" / "judge"
    judge = Judge(GitHub(repo, server, token), ws=None if a.no_gates else Workspace(root, folder),
                  verdicts=Verdicts(folder / "verdicts.json"), dry_run=a.dry_run, port=a.port,
                  timeout=a.gates_timeout * 60, only=a.pr)
    print(f"judging {repo} on {server}{' (dry run)' if a.dry_run else ''}{' (guards only)' if a.no_gates else ''}")
    if a.once:
        try:
            judge.drain()
        except (RuntimeError, urllib.error.URLError) as e:
            print(f"pass failed: {e}")
            return 1
        if a.pr is None:
            return 0
        ok, line = judge.verdict(a.pr)
        print(line)
        return 0 if ok or a.dry_run else 1
    while True:
        try:
            judge.run_pass()
        except (RuntimeError, urllib.error.URLError) as e:
            print(f"pass failed: {e}")
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
