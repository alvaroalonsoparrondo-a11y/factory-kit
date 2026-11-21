#!/usr/bin/env python3
"""The ticket board as a live page on your own machine.

Part of the judge. Human-owned. Standard library only (Python 3.11+).

  python harness/board/serve.py [--port 8765] [--root .] [--quiet-minutes 10]

Then open http://127.0.0.1:8765. It reads what board.py reads: Git (it runs `git fetch`
every 30 seconds), the BMAD files, and GitHub through your own `gh` login (`gh auth token`)
or GITHUB_TOKEN. With neither, it shows Git only: no pull requests or checks.
The GitHub host (github.com or GitHub Enterprise) comes from `origin`; GITHUB_SERVER_URL and
GITHUB_API_URL override it.

The branch checked out here, and every `story/*` branch checked out in another worktree
of this repository, is read from its working tree, so a running lap shows its plan
before it is pushed, wherever it runs. It also reads each lap's stops from `.lap/<ref>.jsonl`
(written by lap_signal.py) and shows a running lap as quiet when nothing in its working tree
has changed for --quiet-minutes.
"""
import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import board as b

HERE = Path(__file__).resolve().parent
CACHE_SECONDS = 5
FETCH_SECONDS = 30
GITHUB_SECONDS = 60


_REMOTE = re.compile(r"^(?:https?://(?:[^@/]+@)?([^/]+)/|git@([^:]+):)([^/]+)/([^/]+?)(?:\.git)?/?$")


def repo_from_url(url):
    """`owner/name` from a GitHub remote URL (github.com or a GitHub Enterprise host), or None."""
    m = _REMOTE.match(url.strip())
    return f"{m.group(3)}/{m.group(4)}" if m else None


def server_from_url(url):
    """`https://<host>` of a GitHub remote URL, or None."""
    m = _REMOTE.match(url.strip())
    return f"https://{m.group(1) or m.group(2)}" if m else None


def api_for(server):
    """REST API root for a GitHub server: api.github.com, or <server>/api/v3 on GitHub Enterprise."""
    server = server.rstrip("/")
    return "https://api.github.com" if server == "https://github.com" else f"{server}/api/v3"


def gh_token(server=None):
    """GITHUB_TOKEN, else `gh auth token` for the server's host (gh's default host if none is given)."""
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    host = server.split("://", 1)[-1].rstrip("/") if server else None
    try:
        done = subprocess.run(["gh", "auth", "token", *(["--hostname", host] if host else [])],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


class GhCliGitHub:
    """GitHub through `gh api`, for machines where Python cannot verify GitHub's certificate.

    On Windows, Python trusts only the root certificates already in the system store, while
    `gh` lets Windows fetch a missing root on demand.
    """

    def __init__(self, repo):
        self.repo = repo

    def get(self, path, key=None):
        url = f"repos/{self.repo}{path}{'&' if '?' in path else '?'}per_page=100"
        try:
            done = subprocess.run(["gh", "api", "--paginate", "--slurp", url],
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(f"gh api {path}: {e}") from e
        if done.returncode != 0:
            raise RuntimeError(f"gh api {path}: {done.stderr.strip()}")
        pages = json.loads(done.stdout or "[]")
        if key:
            return [item for page in pages for item in page.get(key, [])]
        if pages and isinstance(pages[0], list):
            return [item for page in pages for item in page]
        return pages[0] if pages else {}


class FallbackGitHub:
    """Python's own HTTPS first; on a certificate error, `gh api` from then on."""

    def __init__(self, direct, repo):
        self.direct, self.repo, self.via_gh = direct, repo, False

    def get(self, path, key=None):
        if not self.via_gh:
            try:
                return self.direct.get(path, key)
            except urllib.error.URLError as e:
                if not isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError) or not shutil.which("gh"):
                    raise
                self.via_gh = True
        return GhCliGitHub(self.repo).get(path, key)


class CachedGitHub:
    """GitHub answers kept for GITHUB_SECONDS, so polling the page stays far below the API's hourly limit."""

    def __init__(self, gh, seconds):
        self.gh, self.seconds, self.repo = gh, seconds, gh.repo
        self.answers = {}

    def get(self, path, key=None):
        at, value = self.answers.get((path, key), (0.0, None))
        if value is None or time.time() - at > self.seconds:
            value = self.gh.get(path, key)
            self.answers[(path, key)] = (time.time(), value)
        return value


class NoGitHub:
    """Stands in for GitHub when there is no token: no pull requests, so no checks."""

    def __init__(self, repo):
        self.repo = repo

    def get(self, path, key=None):
        return []


def working_files(root):
    """{path: text} of the BMAD tickets and plans in the working tree, like board.bmad_files."""
    out = {}
    base = Path(root) / b.BMAD_DIR
    for p in base.rglob("*"):
        if p.is_file() and (p.name == "tickets.toml" or p.name.endswith("-plan.md")):
            out[p.relative_to(root).as_posix()] = p.read_text(encoding="utf-8")
    return out


def parse_worktrees(porcelain):
    """{branch: path} of the `story/*` branches checked out in worktrees, from
    `git worktree list --porcelain`. Worktrees whose folder is gone are left out."""
    out, path = {}, None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/story/") and path:
            if Path(path).is_dir():
                out[line[len("branch refs/heads/"):]] = path
        elif not line.strip():
            path = None
    return out


ACTIVITY_SECONDS = 30
SKIP_DIRS = {".git", "node_modules", ".lap"}


def read_signals(root, problems, out=None):
    """{ref: [signal, ...]} from `.lap/<ref>.jsonl`, the lap's own record of its stops.

    Pass `out` to add one working tree's signals to those of others."""
    out = {} if out is None else out
    folder = Path(root) / ".lap"
    if not folder.is_dir():
        return out
    for p in sorted(folder.glob("*.jsonl")):
        events = []
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                problems.append(f"`.lap/{p.name}` line {n} cannot be read.")
                continue
            if isinstance(event, dict):
                events.append(event)
        out.setdefault(p.stem, []).extend(events)
    return out


def newest_change(root):
    """The newest change time of any file or folder in the working tree, build output included.

    A folder holding its own `.git` (a worktree nested here, as under `.claude/worktrees/`) is
    another working tree and is left out, so another lap's work never keeps this one awake."""
    newest = 0.0
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not os.path.exists(os.path.join(folder, d, ".git"))]
        for name in [*files, *dirs]:
            try:
                newest = max(newest, os.stat(os.path.join(folder, name)).st_mtime)
            except OSError:
                pass  # removed while we looked
    return newest


def branch_times(root):
    """{branch: newest commit time} for local and remote `story/` branches."""
    out = {}
    lines = b.git(root, "for-each-ref", "--format=%(refname:short) %(committerdate:unix)",
                  "refs/heads/story", "refs/remotes/origin/story").splitlines()
    for line in lines:
        name, _, at = line.rpartition(" ")
        if name and at.isdigit():
            name = name.removeprefix("origin/")
            out[name] = max(out.get(name, 0), int(at))
    return out


def minutes(seconds):
    return f"{int(seconds // 60)} min"


def ticket_markdown(t, row):
    """The ticket entry as a document for the drawer."""
    out = [f"# {t['ref']}: {t['title']}", ""]
    facts = [f"Stage: {row['stage']}", f"Status: {row['status']}"]
    if t.get("risk"):
        facts.append(f"Risk: {t['risk']}")
    if t.get("covers"):
        facts.append("Covers: " + ", ".join(t["covers"]))
    if t.get("after"):
        facts.append("After: " + ", ".join(f"#{a}" for a in t["after"]))
    out += [" · ".join(facts), ""]
    if row.get("needs_you"):
        out += [f"**Needs you:** {row['needs_you']}", ""]
    if row.get("blocked"):
        out += [f"**Blocked:** {row['blocked']}", ""]
    if row.get("stops"):
        out += ["## Stops for you", "",
                "From the lap's own signals (`.lap/`): what the agent said, not evidence about the work.", "",
                "| Since | Kind | What was needed | Waited |", "|---|---|---|---|"]
        for s in row["stops"]:
            waited = minutes(s["seconds"]) + (" so far" if s["open"] else "")
            out.append(f"| {s['at']} | {b._cell(s['kind'])} | {b._cell(s['text'])} | {waited} |")
        hw = row["human_wait"]
        out += ["", f"{hw['stops']} stop{'s' if hw['stops'] != 1 else ''}, {minutes(hw['seconds'])} in total.", ""]
    findings = (row.get("reviews") or {}).get("findings")
    if findings:
        out += [f"**Reviews:** {row['reviews']['bmad']} BMAD passes, {b.findings_text(findings)}.", ""]
    if t.get("description"):
        out += ["## Description", "", t["description"], ""]
    if t.get("verify"):
        out += ["## Verify", "", t["verify"], ""]
    if t.get("notes"):
        out += ["## Notes", ""] + [f"- {n}" for n in t["notes"]] + [""]
    return "\n".join(out)


class Source:
    def __init__(self, root, repo, gh, server, quiet_seconds=600):
        self.root, self.repo, self.gh, self.server = root, repo, gh, server
        self.quiet_seconds = quiet_seconds
        self.lock = threading.Lock()
        self.fetched = 0.0
        self.looked = {}  # folder: (when it was last walked, its newest change then)
        self.cached = (0.0, None, None)  # time, board, snapshot
        self.error = None

    def _git(self, *args):
        return b.git(self.root, *args)

    def current_branch(self):
        try:
            return self._git("rev-parse", "--abbrev-ref", "HEAD").strip()
        except RuntimeError:
            return ""

    def live_trees(self):
        """{branch: folder} for every branch whose files are read from a working tree:
        the one checked out here, plus `story/*` branches in other worktrees."""
        try:
            trees = parse_worktrees(self._git("worktree", "list", "--porcelain"))
        except RuntimeError:
            trees = {}
        branch = self.current_branch()
        if branch:
            trees[branch] = self.root
        return trees

    def snapshot(self):
        if time.time() - self.fetched > FETCH_SECONDS:
            try:
                self._git("fetch", "--quiet", "--prune", "origin")
            except RuntimeError:
                pass  # offline: show what the last fetch saw
            self.fetched = time.time()
        snap = b.collect(self.root, self.gh, self.server)
        # The checked-out branch: read its plans (and, on main, its tickets) from the working tree.
        branch = self.current_branch()
        files = working_files(self.root)
        if branch == "main":
            snap["plans"]["main"] = b.read_plans(files)
            snap["tickets"] = b.read_tickets(files, snap["problems"])
        for ref, folder in self.live_trees().items():
            if not ref.startswith("story/"):
                continue
            snap["plans"][ref] = b.read_plans(files if folder == self.root else working_files(folder))
            if ref not in snap["branches"]:
                snap["branches"].append(ref)
        dirty = bool(self._git("status", "--porcelain").strip())
        snap["local"] = {"branch": branch, "dirty": dirty, "github": not isinstance(self.gh, NoGitHub)}
        # Each lap's signals, and whether the working tree it runs in has gone quiet.
        now = time.time()
        trees = self.live_trees()
        signals, idle = {}, {}
        for folder in dict.fromkeys([self.root, *trees.values()]):
            read_signals(folder, snap["problems"], signals)
        for ref, folder in trees.items():
            if not ref.startswith("story/"):
                continue
            at, newest = self.looked.get(folder, (0.0, 0.0))
            if now - at > ACTIVITY_SECONDS:
                at, newest = now, newest_change(folder)
                self.looked[folder] = (at, newest)
            idle[ref] = max(now - newest, 0)
        snap["now"] = now
        snap["signals"] = signals
        snap["branch_times"] = branch_times(self.root)
        snap["activity"] = {"idle_seconds": idle, "quiet_seconds": self.quiet_seconds}
        return snap

    def refresh(self):
        """Rebuild the board; the page keeps the last good one while this runs."""
        try:
            snap = self.snapshot()
            board = b.derive(snap)
            board["local"] = snap["local"]
            board["server"] = self.server
            board["built_at"] = time.strftime("%H:%M:%S")
            with self.lock:
                self.cached = (time.time(), board, snap)
                self.error = None
        except (RuntimeError, urllib.error.URLError, KeyError, OSError) as e:
            with self.lock:
                self.error = f"could not read the board: {e}"

    def run(self):
        """Refresh every CACHE_SECONDS, forever (a daemon thread)."""
        while True:
            self.refresh()
            time.sleep(CACHE_SECONDS)

    def board(self):
        with self.lock:
            _, board, snap = self.cached
            error = getattr(self, "error", None)
        if board is None:
            raise RuntimeError(error or "the board is still loading")
        if error:
            board = {**board, "problems": [f"Not refreshed: {error}"] + board["problems"]}
        return board, snap

    def _read(self, ref, path):
        """A file from the working tree when `ref` is checked out here, else from `origin/<ref>`."""
        folder = self.live_trees().get(ref)
        if folder:
            p = Path(folder) / path
            return p.read_text(encoding="utf-8") if p.is_file() else None
        try:
            return self._git("show", f"origin/{ref}:{path}")
        except RuntimeError:
            return None

    def docs(self, epic, ticket_id):
        board, snap = self.board()
        row = next((r for e in board["epics"] for r in e["rows"]
                    if r["epic"] == epic and r["id"] == ticket_id), None)
        t = next((t for t in snap["tickets"] if t["epic"] == epic and t["id"] == ticket_id), None)
        if row is None or t is None:
            return None
        docs = [{"name": "ticket", "text": ticket_markdown(t, row)}]
        # A finished ticket's plan is read from main, where it was merged; a running one from its branch.
        ref = "main" if row["stage"] in ("Done", "Dropped") or not row["branch"] else row["branch"]
        if row["plan_path"]:
            text = self._read(ref, row["plan_path"]) or self._read("main", row["plan_path"])
            if text:
                docs.append({"name": "plan", "text": text})
        pr_file = Path(self.live_trees().get(row["branch"] or "", self.root)) / ".lap" / f"{row['ref']}-pr.md"
        if pr_file.is_file():
            docs.append({"name": "pull request", "text": pr_file.read_text(encoding="utf-8")})
        epic_path = re.sub(r"/tickets/tickets\.toml$", f"/{epic}.md", t["source"])
        text = self._read("main", epic_path)
        if text:
            docs.append({"name": "epic", "text": text})
        return docs


def make_handler(source):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, kind):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, value):
            self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            url = urlparse(self.path)
            try:
                if url.path == "/":
                    return self._send(200, (HERE / "dashboard.html").read_bytes(), "text/html; charset=utf-8")
                if url.path == "/board.json":
                    return self._json(200, source.board()[0])
                if url.path == "/docs.json":
                    q = parse_qs(url.query)
                    docs = source.docs(q.get("epic", [""])[0], q.get("id", [""])[0])
                    return self._json(200, docs) if docs is not None else self._json(404, {"error": "no such ticket"})
                return self._json(404, {"error": "not found"})
            except (RuntimeError, urllib.error.URLError, KeyError) as e:
                return self._json(502, {"error": f"could not read the board: {e}"})

        def log_message(self, *args):
            pass

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="Serve the ticket board as a live local page.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--root", default=".", help="the repository (default: current folder)")
    ap.add_argument("--quiet-minutes", type=float, default=10,
                    help="a running lap with no file change for this long shows as quiet (default: 10)")
    args = ap.parse_args(argv)

    root = b.git(args.root, "rev-parse", "--show-toplevel").strip()
    origin = b.git(root, "remote", "get-url", "origin")
    repo = os.environ.get("GITHUB_REPOSITORY") or repo_from_url(origin)
    if not repo:
        print("serve: origin is not a GitHub repository; set GITHUB_REPOSITORY", file=sys.stderr)
        return 2
    server = os.environ.get("GITHUB_SERVER_URL") or server_from_url(origin) or "https://github.com"
    token = gh_token(server)
    api = os.environ.get("GITHUB_API_URL") or api_for(server)
    gh = CachedGitHub(FallbackGitHub(b.GitHub(repo, token, api), repo), GITHUB_SECONDS) if token else NoGitHub(repo)
    source = Source(root, repo, gh, server, quiet_seconds=args.quiet_minutes * 60)
    threading.Thread(target=source.run, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(source))
    print(f"Board for {repo} at http://127.0.0.1:{args.port}"
          + ("" if token else " (no GitHub token: Git only)") + ". Ctrl+C stops it.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
