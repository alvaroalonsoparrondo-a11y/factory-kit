#!/usr/bin/env python3
"""Builds the ticket board: one row per ticket, read from Git, GitHub and the BMAD files.

Part of the judge. Human-owned. Standard library only (Python 3.11+).

  python3 harness/board/board.py --out <dir>             collect, then write BOARD.md and board.json
  python3 harness/board/board.py --out <dir> --snapshot f.json   skip collection, use recorded inputs
  python3 harness/board/board.py --dump-snapshot f.json   also save the collected inputs

Environment for collection: GITHUB_REPOSITORY (owner/name), GITHUB_TOKEN,
GITHUB_API_URL (default https://api.github.com), GITHUB_SERVER_URL (default https://github.com).

The board has no state of its own. Nothing here reads the holdouts repository:
a failing hidden scenario is known only by the ID in the `holdouts` commit status.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

CHECKS = ("gates", "protected-paths", "scope-guard", "holdouts")
GUARDS = ("protected-paths", "scope-guard")
PLAN_STATUSES = ("draft", "ready-for-dev", "in-progress", "in-review", "built", "done", "blocked", "dropped")
MARK = {"green": "✅", "red": "❌", "running": "⏳", "missing": "➖"}
BMAD_DIR = "_bmad-output"


# --------------------------------------------------------------------------- collection

def parse_frontmatter(text):
    """The `key: value` lines between the first two `---` lines, as strings."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        value = m.group(2).strip()
        if value[:1] in ("'", '"'):
            end = value.find(value[0], 1)
            value = value[1:end] if end > 0 else value[1:]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        out[m.group(1)] = value
    return out


def epic_of(path):
    """`.../tickets/<epic>/tickets/<file>` -> `<epic>`; a file elsewhere belongs to its folder."""
    parts = path.split("/")
    if len(parts) >= 3 and parts[-2] == "tickets":
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else ""


def git(root, *args):
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def bmad_files(root, ref):
    """{path: text} of every tickets.toml and plan file under the BMAD output folder at `ref`."""
    try:
        names = git(root, "ls-tree", "-r", "--name-only", ref, "--", BMAD_DIR).splitlines()
    except RuntimeError:
        return {}
    wanted = [n for n in names if n.endswith("/tickets.toml") or n.endswith("-plan.md")]
    return {n: git(root, "show", f"{ref}:{n}") for n in wanted}


def read_tickets(files, problems):
    tickets = []
    for path in sorted(p for p in files if p.endswith("/tickets.toml")):
        try:
            data = tomllib.loads(files[path])
        except tomllib.TOMLDecodeError as e:
            problems.append(f"`{path}` cannot be read: {e}")
            continue
        for entry in data.get("entry", []):
            if "id" not in entry:
                problems.append(f"`{path}` has an entry without an id")
                continue
            tickets.append({
                "epic": epic_of(path),
                "id": str(entry["id"]),
                "title": str(entry.get("title", "")),
                "after": [str(a) for a in entry.get("after", []) if isinstance(a, (int, str))],
                "hitl": bool(entry.get("hitl", False)),
                "risk": str(entry.get("risk", "")),
            })
    return tickets


def read_plans(files):
    plans = []
    for path in sorted(p for p in files if p.endswith("-plan.md")):
        fm = parse_frontmatter(files[path])
        if not fm.get("ticket"):
            continue
        plans.append({
            "path": path,
            "epic": epic_of(path),
            "ticket": fm["ticket"],
            "status": fm.get("status", ""),
            "review": fm.get("review", ""),
            "review_loop_iteration": fm.get("review_loop_iteration", "0"),
            "blocked_at": fm.get("blocked_at", ""),
            "blocked_reason": fm.get("blocked_reason", ""),
        })
    return plans


class GitHub:
    def __init__(self, repo, token, api="https://api.github.com"):
        self.repo, self.token, self.api = repo, token, api.rstrip("/")

    def get(self, path, key=None):
        """Every page of a list endpoint. `key` names the list inside an object response."""
        url = f"{self.api}/repos/{self.repo}{path}{'&' if '?' in path else '?'}per_page=100"
        items = []
        while url:
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "factory-board",
            })
            for attempt in range(3):  # a network hiccup should not cost a rebuild
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        body = json.load(resp)
                        link = resp.headers.get("Link", "")
                    break
                except urllib.error.HTTPError:
                    raise
                except urllib.error.URLError:
                    if attempt == 2:
                        raise
                    time.sleep(2)
            if key is None and not isinstance(body, list):
                return body
            items.extend(body[key] if key else body)
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = m.group(1) if m else None
        return items


def check_state(status, conclusion):
    if status != "completed":
        return "running"
    return "green" if conclusion in ("success", "neutral", "skipped") else "red"


def commit_checks(gh, sha):
    """{check name: {state, description}} from check runs and commit statuses on one commit."""
    out = {}
    runs = gh.get(f"/commits/{sha}/check-runs", key="check_runs")
    for run in sorted(runs, key=lambda r: r.get("id", 0)):  # the latest run of a name wins
        if run["name"] in CHECKS:
            out[run["name"]] = {"state": check_state(run["status"], run.get("conclusion")), "description": ""}
    combined = gh.get(f"/commits/{sha}/status")
    for st in combined.get("statuses", []):  # already the latest per context
        if st["context"] in CHECKS:
            state = {"success": "green", "pending": "running"}.get(st["state"], "red")
            out[st["context"]] = {"state": state, "description": st.get("description") or ""}
    return out


def collect(root, gh, server="https://github.com"):
    problems = []
    main_files = bmad_files(root, "origin/main")
    branches = [
        b.removeprefix("origin/")
        for b in git(root, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/story").splitlines()
        if b.strip()
    ]
    plans = {"main": read_plans(main_files)}
    for branch in branches:
        plans[branch] = read_plans(bmad_files(root, f"origin/{branch}"))

    pulls = []
    for pr in gh.get("/pulls?state=all"):
        head = pr["head"]
        if not head["ref"].startswith("story/") or (head.get("repo") or {}).get("full_name") != gh.repo:
            continue
        commits = [c["sha"] for c in gh.get(f"/pulls/{pr['number']}/commits")]
        per_commit = {sha: commit_checks(gh, sha) for sha in commits}
        reviews = gh.get(f"/pulls/{pr['number']}/reviews")
        pulls.append({
            "number": pr["number"],
            "url": pr["html_url"],
            "branch": head["ref"],
            "state": pr["state"],
            "merged": bool(pr.get("merged_at")),
            "checks": per_commit.get(head["sha"], {}),
            "judged_commits": sum(1 for c in per_commit.values() if "gates" in c),
            "human_reviews": sum(
                1 for r in reviews
                if (r.get("user") or {}).get("type") == "User" and r.get("state") != "PENDING"
            ),
        })

    return {
        "repo": gh.repo,
        "server": server.rstrip("/"),
        "main_sha": git(root, "rev-parse", "--short", "origin/main").strip(),
        "tickets": read_tickets(main_files, problems),
        "plans": plans,
        "branches": branches,
        "pulls": pulls,
        "problems": problems,
    }


# --------------------------------------------------------------------------- derivation

def _plan_for(plans, epic, ticket_id):
    for plan in plans:
        if plan["epic"] == epic and plan["ticket"] == ticket_id:
            return plan
    return None


def _match_branch(branch, tickets, snapshot):
    """The ticket a `story/<id>` branch belongs to, or None with a reason."""
    ticket_id = branch.removeprefix("story/")
    candidates = [t for t in tickets if t["id"] == ticket_id]
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, f"Branch `{branch}` matches no ticket."
    # Several epics use this id: the epic whose plan this branch adds or changes is the one.
    on_main = snapshot["plans"].get("main", [])
    touched = [
        t for t in candidates
        if (p := _plan_for(snapshot["plans"].get(branch, []), t["epic"], ticket_id))
        and p != _plan_for(on_main, t["epic"], ticket_id)
    ]
    if len(touched) == 1:
        return touched[0], None
    epics = ", ".join(t["epic"] for t in candidates)
    return None, f"Branch `{branch}` could belong to several tickets ({epics}); it is matched once its plan is pushed."


def _pick_pull(pulls):
    """One pull request per branch: a merged one, else the open one, else the newest."""
    for wanted in (lambda p: p["merged"], lambda p: p["state"] == "open"):
        hits = [p for p in pulls if wanted(p)]
        if hits:
            return max(hits, key=lambda p: p["number"])
    return max(pulls, key=lambda p: p["number"]) if pulls else None


def _stage(plan_status, has_branch, pr):
    if plan_status == "dropped":
        return "Dropped"
    if plan_status == "done" or (pr and pr["merged"]):
        return "Done"
    if pr and pr["state"] == "open":
        return "In CI"
    if pr:
        return "PR closed"
    if not has_branch:
        return "Planned"
    return {"in-progress": "Building", "blocked": "Building", "in-review": "In review", "built": "Built"}.get(
        plan_status, "Lap started")


def derive(snapshot):
    problems = list(snapshot.get("problems", []))
    tickets = snapshot["tickets"]
    key = lambda t: (t["epic"], t["id"])

    branch_of, pulls_of = {}, {}
    names = list(dict.fromkeys(snapshot["branches"] + [p["branch"] for p in snapshot["pulls"]]))
    for name in names:
        ticket, why = _match_branch(name, tickets, snapshot)
        if ticket is None:
            problems.append(why)
            continue
        branch_of[key(ticket)] = name
        pulls_of[key(ticket)] = [p for p in snapshot["pulls"] if p["branch"] == name]

    rows = []
    for t in tickets:
        branch = branch_of.get(key(t))
        plan = None
        if branch:
            plan = _plan_for(snapshot["plans"].get(branch, []), *key(t))
        plan = plan or _plan_for(snapshot["plans"].get("main", []), *key(t))
        status = plan["status"] if plan else ""
        if plan and status not in PLAN_STATUSES:
            problems.append(f"`{plan['path']}` has an unknown status `{status}`.")
        pr = _pick_pull(pulls_of.get(key(t), []))
        try:
            loops = int(plan["review_loop_iteration"]) if plan else 0
        except ValueError:
            loops = 0
        reviewed = bool(plan) and plan["review"] not in ("", "none")
        rows.append({
            "epic": t["epic"], "id": t["id"], "title": t["title"], "after": t["after"], "hitl": t["hitl"],
            "branch": branch,
            "stage": _stage(status, bool(branch), pr),
            "blocked": (plan["blocked_reason"] or "no reason given")
            if plan and (status == "blocked" or plan["blocked_at"]) else None,
            "pr": {"number": pr["number"], "url": pr["url"]} if pr else None,
            "checks": {c: (pr["checks"].get(c) or {}).get("state", "missing") for c in CHECKS} if pr else None,
            "holdout_ids": sorted(set(re.findall(
                r"H-\d+", (pr["checks"].get("holdouts") or {}).get("description", "")))) if pr else [],
            "reviews": {
                "bmad": loops + 1 if reviewed else 0,
                "fix_rounds": max(pr["judged_commits"] - 1, 0) if pr else 0,
                "human": pr["human_reviews"] if pr else 0,
            } if branch else None,
        })

    done = {key(r) for r in rows if r["stage"] == "Done"}
    first_ready = set()  # the first startable ticket of each epic
    for r in rows:
        r["waiting_on"] = [a for a in r["after"] if (r["epic"], a) not in done]
        r["needs_you"] = _needs_you(r, snapshot)
        if r["stage"] == "Planned" and not r["waiting_on"] and not r["blocked"] and r["epic"] not in first_ready:
            first_ready.add(r["epic"])
            r["needs_you"] = "Start the lap" + (" (human in the loop)" if r["hitl"] else "")
        r["status"] = _status(r)

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    epics = []
    for name in dict.fromkeys(r["epic"] for r in rows):
        epics.append({"name": name, "rows": [r for r in rows if r["epic"] == name]})
    return {
        "repo": snapshot["repo"], "main_sha": snapshot["main_sha"],
        "counts": counts, "epics": epics, "problems": problems,
    }


def _needs_you(r, snapshot):
    if r["stage"] in ("Done", "Dropped"):
        return None
    if r["blocked"]:
        return f"Decide: {r['blocked']}"
    if r["stage"] == "PR closed":
        return "Closed without merge: decide what happens to the ticket"
    if r["stage"] == "In CI":
        checks = r["checks"]
        red = [c for c in CHECKS if checks[c] == "red"]
        if any(c in GUARDS for c in red):
            return "Review the change: label it or send it back (" + ", ".join(c for c in red if c in GUARDS) + ")"
        if red:
            ids = f": {', '.join(r['holdout_ids'])}" if "holdouts" in red and r["holdout_ids"] else ""
            return f"Paste the failing check into the lap ({', '.join(red)}{ids})"
        if all(checks[c] == "green" for c in CHECKS):
            return "Review and merge"
        missing = [c for c in CHECKS if checks[c] == "missing"]
        if missing and not any(checks[c] == "running" for c in CHECKS):
            return "A required check has not reported: " + ", ".join(missing)
        return None
    if r["stage"] == "Built":
        link = f"{snapshot.get('server', 'https://github.com')}/{snapshot['repo']}/compare/main...{r['branch']}?expand=1"
        return f"[Open the pull request]({link})"
    return None


def _status(r):
    if r["stage"] == "Dropped":
        return "dropped"
    if r["stage"] == "Done":
        return "done"
    if r["blocked"]:
        return "blocked"
    if r["needs_you"]:
        return "needs you"
    if r["stage"] != "Planned":
        return "running"
    return "waiting" if r["waiting_on"] else "ready"


# --------------------------------------------------------------------------- rendering

def _cell(text):
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|").strip()


def render_markdown(board):
    name = board["repo"].split("/")[-1]
    order = ("needs you", "blocked", "running", "ready", "waiting", "done", "dropped")
    summary = " · ".join(f"{board['counts'][s]} {s}" for s in order if board["counts"].get(s))
    out = [f"# Board: {_cell(name)}", "", f"Built from `main` at `{board['main_sha']}`" + (f" · {summary}" if summary else ""), ""]

    if not board["epics"]:
        out += ["No tickets yet. The board fills in once a `tickets.toml` is on `main`.", ""]

    asks = [r for e in board["epics"] for r in e["rows"] if r["needs_you"]]
    out.append("## Needs you now")
    out.append("")
    for r in asks:
        where = f" → [#{r['pr']['number']}]({r['pr']['url']})" if r["pr"] else ""
        out.append(f"- **{_cell(r['epic'])} #{r['id']}** {_cell(r['title'])}: {_cell(r['needs_you'])}{where}")
    if not asks:
        out.append("Nothing.")
    out.append("")

    for epic in board["epics"]:
        out += [f"## {_cell(epic['name'])}", "",
                "| # | Ticket | Stage | Status | Needs you | Checks | Reviews B/F/H | PR |",
                "|---|---|---|---|---|---|---|---|"]
        for r in epic["rows"]:
            needs = _cell(r["needs_you"]) if r["needs_you"] else "–"
            if r["status"] == "waiting":
                needs = "– (after " + ", ".join(f"#{a}" for a in r["waiting_on"]) + ")"
            checks = "–"
            if r["checks"]:
                checks = "".join(MARK[r["checks"][c]] for c in CHECKS)
                if r["holdout_ids"] and r["checks"]["holdouts"] == "red":
                    checks += " " + ", ".join(r["holdout_ids"])
            rv = r["reviews"]
            reviews = f"{rv['bmad']}/{rv['fix_rounds']}/{rv['human']}" if rv else "–"
            pr = f"[#{r['pr']['number']}]({r['pr']['url']})" if r["pr"] else "–"
            out.append(f"| {r['id']} | {_cell(r['title'])} | {r['stage']} | {r['status']} | {needs} | {checks} | {reviews} | {pr} |")
        out.append("")

    out += ["## Problems", ""]
    out += [f"- {p}" for p in board["problems"]] or ["None."]
    out += ["", "---", "",
            "Checks, in order: `gates`, `protected-paths`, `scope-guard`, `holdouts` "
            f"({MARK['green']} green, {MARK['red']} red, {MARK['running']} running, {MARK['missing']} not reported). "
            "Reviews: BMAD review passes / fix rounds / human reviews. "
            "Built by the `board` workflow; do not edit by hand.", ""]
    return "\n".join(out)


def render_json(board):
    return json.dumps(board, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the ticket board.")
    ap.add_argument("--out", help="folder to write BOARD.md and board.json into")
    ap.add_argument("--snapshot", help="use recorded inputs instead of collecting")
    ap.add_argument("--dump-snapshot", help="save the collected inputs to this file")
    ap.add_argument("--root", default=".", help="the repository (default: current folder)")
    args = ap.parse_args(argv)

    if args.snapshot:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    else:
        repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
        if not repo or not token:
            print("board: set GITHUB_REPOSITORY and GITHUB_TOKEN, or pass --snapshot", file=sys.stderr)
            return 2
        gh = GitHub(repo, token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
        try:
            snapshot = collect(args.root, gh, os.environ.get("GITHUB_SERVER_URL", "https://github.com"))
        except (urllib.error.URLError, RuntimeError, KeyError) as e:
            print(f"board: could not collect, nothing written: {e!r}", file=sys.stderr)
            return 1
    if args.dump_snapshot:
        Path(args.dump_snapshot).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    board = derive(snapshot)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "BOARD.md").write_text(render_markdown(board), encoding="utf-8", newline="\n")
        (out / "board.json").write_text(render_json(board), encoding="utf-8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(render_markdown(board))
    return 0


if __name__ == "__main__":
    sys.exit(main())
