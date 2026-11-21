#!/usr/bin/env python3
"""The factory judge, for GitHub hosts where Actions is not allowed. Human-owned.

Part of the judge. Standard library only (Python 3.11+).

  python harness/judge/judge.py [--root .] [--once] [--interval 120] [--dry-run]

Each pass reads the open pull requests and posts the commit statuses that
`.github/workflows/judge-guards.yml` would post as checks: `protected-paths` and
`scope-guard`, judged by `guards.py` from the changed file names and the labels. The board,
the dispatcher and branch protection already read commit statuses, so nothing else changes.
It never checks out or runs pull request code. A status is posted only when it changes.

Not yet: `gates`, `calibrate` and the board rebuild (see RUNBOOK.md, "Without GitHub Actions").

GitHub: FACTORY_JUDGE_TOKEN, else GITHUB_TOKEN, else `gh auth token` for origin's host. The token
needs Pull requests read and Commit statuses write. Never give it to a lap.
"""
import argparse
import json
import os
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


class GitHub:
    """Reads through the board's client; writes the one thing the judge writes, a commit status."""

    def __init__(self, repo, server, token):
        self.repo, self.token, self.api = repo, token, serve.api_for(server)
        self.reader = serve.FallbackGitHub(board.GitHub(repo, token, self.api), repo) if token \
            else serve.GhCliGitHub(repo)

    def get(self, path, key=None):
        return self.reader.get(path, key)

    def post_status(self, sha, context, state, description):
        body = {"state": state, "context": context, "description": description}
        if self.token and not getattr(self.reader, "via_gh", False):
            req = urllib.request.Request(f"{self.api}/repos/{self.repo}/statuses/{sha}",
                                         data=json.dumps(body).encode(), method="POST", headers={
                                             "Authorization": f"Bearer {self.token}",
                                             "Accept": "application/vnd.github+json",
                                             "X-GitHub-Api-Version": "2022-11-28",
                                             "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30):
                return
        done = subprocess.run(["gh", "api", "-X", "POST", f"repos/{self.repo}/statuses/{sha}", "--input", "-"],
                              input=json.dumps(body), capture_output=True, text=True, encoding="utf-8", timeout=60)
        if done.returncode != 0:
            raise RuntimeError(f"posting {context} on {sha[:7]}: {done.stderr.strip()}")


class Judge:
    def __init__(self, gh, dry_run=False, out=print):
        self.gh, self.dry_run, self.out = gh, dry_run, out

    def judge_pull(self, pr, template):
        """Post this pull request's guard statuses where they changed. Returns what was posted."""
        sha = pr["head"]["sha"]
        labels = [label["name"] for label in pr.get("labels", [])]
        files = self.gh.get(f"/pulls/{pr['number']}/files")
        current = {s["context"]: s for s in self.gh.get(f"/commits/{sha}/status").get("statuses", [])}
        posted = []
        for check in guards.CHECKS:
            passed, hits, message = guards.judge(check, files, labels, template)
            state, text = ("success" if passed else "failure"), guards.description(passed, hits, message)
            now = current.get(check)
            if now and now.get("state") == state and (now.get("description") or "") == text:
                continue
            verb = "would post" if self.dry_run else "posted"
            if not self.dry_run:
                self.gh.post_status(sha, check, state, text)
            posted.append((pr["number"], check, state))
            self.out(f"#{pr['number']} {sha[:7]} {check}: {verb} {state} ({text})")
        return posted

    def run_pass(self):
        template = bool(self.gh.get("").get("is_template"))
        posted = []
        pulls = self.gh.get("/pulls?state=open")
        for pr in pulls:
            try:
                posted += self.judge_pull(pr, template)
            except (RuntimeError, urllib.error.URLError) as e:  # one bad pull request does not stop the rest
                self.out(f"#{pr['number']}: not judged this pass: {e}")
        self.out(f"pass done: {len(pulls)} open pull request(s), {len(posted)} status(es) "
                 f"{'to post' if self.dry_run else 'posted'}")
        return posted


def origin(root):
    url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                         capture_output=True, text=True, check=True).stdout.strip()
    repo, server = serve.repo_from_url(url), serve.server_from_url(url)
    if not repo:
        raise SystemExit(f"cannot read owner/name from origin {url}")
    return repo, os.environ.get("GITHUB_SERVER_URL", server)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", default=".", help="a clone of the project (only its origin is read)")
    p.add_argument("--once", action="store_true", help="one pass, then exit")
    p.add_argument("--interval", type=int, default=120, help="seconds between passes (default 120)")
    p.add_argument("--dry-run", action="store_true", help="print what would be posted, post nothing")
    a = p.parse_args(argv)
    repo, server = origin(Path(a.root))
    token = os.environ.get("FACTORY_JUDGE_TOKEN") or serve.gh_token(server)
    judge = Judge(GitHub(repo, server, token), dry_run=a.dry_run)
    print(f"judging {repo} on {server}{' (dry run)' if a.dry_run else ''}")
    while True:
        try:
            judge.run_pass()
        except (RuntimeError, urllib.error.URLError) as e:
            print(f"pass failed: {e}")
            if a.once:
                return 1
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
