#!/usr/bin/env python3
"""Records a ticket's triage decision and says whether it still holds.

Part of the judge. Human-owned: an agent may run it and may not change it.
Standard library only (Python 3.11+).

  python harness/board/triage.py <ref> check                 none | fresh <state> | stale <state>: <why>
  python harness/board/triage.py <ref> record <decision.json>  check a decision and write docs/triage/<ref>.json
  python harness/board/triage.py <ref> record <decision.json> --push   ... and commit it straight onto main

A decision comes from the `triage` skill: one JSON object with `state`, `summary`, `rationale`,
`questions` and `next_step`. `record` checks it, stamps it with the commit of `origin/main` and a
fingerprint of the ticket, and writes `docs/triage/<ref>.json` in this checkout. With `--push` it
fetches first and commits the file straight onto `main` from a throwaway worktree instead, the way
the dispatcher records its triages, so no checkout changes and nobody commits it by hand.
Everything is read from `origin/main` (`--rev` to change), so a branch's copy of a decision never
counts.

A decision goes stale when, on main since it was made:
- the ticket's entry, its leaf file or its epic file changed (Sofia refined it, a decision landed);
- the set of its `after` prerequisites that are done changed (the ticket before it merged), except
  that a prerequisite getting done never makes a `ready-to-implement` decision stale: triage only
  says ready-to-implement when an open prerequisite cannot change the ticket's intent, and what its
  merge changed in the code is still caught by `touches` below. Without that, a ticket prepared while
  its prerequisite's lap runs would go stale exactly when it becomes ready to start (issue #44);
- a path in its `touches` changed (any code path when the entry has no `touches`).
A stale decision is no decision: the ticket is triaged again.

`plan` in a ready-to-implement decision says who approves the lap's plan: `lap` (the lap approves its
own plan when it has no open questions) or `human` (the entry has `risk = "high"` or `hitl = true`).

A ticket is *prepared* when its leaf file says `refined: true` (the human approved its "what" ahead) and
its decision is a fresh ready-to-implement. Then `check` prints `prepared: <leaf path>` in place of the
`plan:` line: the lap approves its own plan whatever `plan` says, and hands the ticket back instead of
waiting for the human.
"""
import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import posixpath
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board  # noqa: E402

STATES = ("ready-to-implement", "ready-to-spec", "needs-info", "wait")
RECORD_DIR = "docs/triage"
# Changes under these never make a decision stale by themselves: decisions, and BMAD bookkeeping
# (the ticket's own files are covered by its fingerprint).
NOT_CODE = (RECORD_DIR + "/", board.BMAD_DIR + "/", ".lap/", ".factory/")
_cache = {}


def git(root, *args, check=True):
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout if done.returncode == 0 else None


def record_path(ref):
    return f"{RECORD_DIR}/{ref}.json"


# --------------------------------------------------------------------------- the decision

def parse_decision(text):
    """The last JSON object in `text` that has a `state` (an agent's final message, maybe with log lines)."""
    found, at = None, 0
    decoder = json.JSONDecoder()
    while True:
        start = text.find("{", at)
        if start < 0:
            return found
        try:
            obj, end = decoder.raw_decode(text, start)
        except ValueError:
            at = start + 1
            continue
        if isinstance(obj, dict) and "state" in obj:
            found = obj
        at = end


def validate(decision, ticket):
    """The decision, cleaned; raises ValueError when it cannot be recorded."""
    if not isinstance(decision, dict):
        raise ValueError("the decision is not a JSON object")
    state = str(decision.get("state", "")).strip().lower().replace(" ", "-").replace("_", "-")
    state = {"ready-to-build": "ready-to-implement", "wait-to-implement": "wait"}.get(state, state)
    if state not in STATES:
        raise ValueError(f"unknown state {decision.get('state')!r}; one of {', '.join(STATES)}")
    ref = str(decision.get("ref") or ticket["ref"])
    if ref != ticket["ref"]:
        raise ValueError(f"the decision is for {ref}, not {ticket['ref']}")
    strings = lambda key: [str(x).strip() for x in (decision.get(key) or []) if str(x).strip()]
    out = {"ref": ref, "state": state, "summary": str(decision.get("summary", "")).strip(),
           "rationale": strings("rationale"), "questions": strings("questions"),
           "next_step": str(decision.get("next_step", "")).strip()}
    if not out["summary"]:
        raise ValueError("the decision has no summary")
    if state in ("ready-to-spec", "needs-info") and not out["questions"]:
        raise ValueError(f"{state} needs at least one question")
    if state == "ready-to-implement":
        if out["questions"]:
            raise ValueError("ready-to-implement with open questions: choose ready-to-spec or needs-info")
        human = [why for why, on in (('risk = "high"', ticket.get("risk") == "high"), ("hitl = true", ticket.get("hitl")))
                 if on]
        out["plan"] = "human" if human else "lap"
        if human:
            out["rationale"].append(f"The entry has {' and '.join(human)}: a human approves the lap's plan.")
    return out


# --------------------------------------------------------------------------- what the decision rests on

def _tickets_dir(ticket):
    return posixpath.dirname(ticket["source"])


def ticket_texts(root, rev, ticket):
    """{name: text} of what the ticket's intent is made of: its raw entry, its leaf file, its epic file."""
    out = {}
    raw = git(root, "show", f"{rev}:{ticket['source']}", check=False) or ""
    try:
        entries = tomllib.loads(raw).get("entry", [])
    except tomllib.TOMLDecodeError:
        entries = []
    entry = next((e for e in entries if str(e.get("id")) == ticket["id"]), None)
    out["entry"] = json.dumps(entry, sort_keys=True, default=str)
    tickets_dir = _tickets_dir(ticket)
    epic_dir = posixpath.dirname(tickets_dir)
    epic_file = f"{epic_dir}/{posixpath.basename(epic_dir)}.md"
    out[epic_file] = git(root, "show", f"{rev}:{epic_file}", check=False) or ""
    for name, text in _leaf_files(root, rev, ticket):
        out[name] = text
    return out


def _leaf_files(root, rev, ticket):
    """[(path, text)] of the ticket's leaf files: the `.md` files beside its tickets.toml whose frontmatter
    `id` is the entry's."""
    tickets_dir = _tickets_dir(ticket)
    names = (git(root, "ls-tree", "--name-only", rev, tickets_dir + "/", check=False) or "").splitlines()
    out = []
    for name in names:
        if not name.endswith(".md") or name.endswith("-plan.md"):
            continue
        text = git(root, "show", f"{rev}:{name}", check=False) or ""
        if str(board.parse_frontmatter(text).get("id", "")).strip("'\"") == ticket["id"]:
            out.append((name, text))
    return out


def leaf_file(root, rev, ticket):
    """(path, frontmatter) of the ticket's leaf file, or None when it has none."""
    leaves = _leaf_files(root, rev, ticket)
    if not leaves:
        return None
    name, text = leaves[0]
    return name, board.parse_frontmatter(text)


def prepared(root, rev, ticket, record, fresh):
    """The leaf file's path when the ticket is prepared: the human approved its "what" ahead (leaf file
    `refined: true`) and its triage is a fresh ready-to-implement. Else None. A prepared ticket's lap
    approves its own plan and never waits for the human (docs/specs/2026-11-24-early-intent-approval-design.md)."""
    if not (fresh and record and record.get("state") == "ready-to-implement"):
        return None
    leaf = leaf_file(root, rev, ticket)
    if leaf is None:
        return None
    path, fm = leaf
    return path if str(fm.get("refined", "")).strip("'\"").strip().lower() == "true" else None


def fingerprint(root, rev, ticket):
    h = hashlib.sha256()
    for name, text in sorted(ticket_texts(root, rev, ticket).items()):
        h.update(name.encode() + b"\0" + text.replace("\r\n", "\n").encode("utf-8") + b"\0")
    return h.hexdigest()[:16]


def done_prereqs(ticket, plans):
    """The ticket's `after` ids whose plan on main says done."""
    done = {p["ticket"] for p in plans if p["epic"] == ticket["epic"] and p["status"] == "done"}
    return sorted(a for a in ticket["after"] if a in done)


def _touched(path, patterns):
    if patterns is None:
        return not path.startswith(NOT_CODE)
    for p in patterns:
        if fnmatch.fnmatchcase(path, p) or (p.endswith("/**") and path.startswith(p[:-2])):
            return True
    return False


# --------------------------------------------------------------------------- record and check

def build_record(decision, root, rev, ticket, plans, now=None):
    out = validate(decision, ticket)
    out.update({
        "triaged_at": now or dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "main_sha": git(root, "rev-parse", rev).strip(),
        "fingerprint": fingerprint(root, rev, ticket),
        "prereqs_done": done_prereqs(ticket, plans),
    })
    return out


def write_record(folder, record):
    path = Path(folder) / record_path(record["ref"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def commit_to_main(root, prefix, change, folder, message):
    """Run `change(tmp)` in a throwaway detached worktree of origin/main, commit what it changed under
    `folder` and push it straight onto main, so no checkout is disturbed. Never force-pushes; when main
    moved meanwhile, rebases the one unpushed commit and pushes again. The new main commit, or None when
    nothing changed. Shared by `record --push` and the dispatcher."""
    def run(*args, cwd, check=True):
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
        if check and done.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
        return done

    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    tmp.rmdir()
    run("worktree", "add", "--quiet", "--detach", str(tmp), "origin/main", cwd=root)
    try:
        change(tmp)
        run("add", "-A", folder, cwd=tmp)
        if not run("diff", "--cached", "--quiet", cwd=tmp, check=False).returncode:
            return None  # nothing changed
        run("commit", "--quiet", "-m", message, cwd=tmp)
        if run("push", "--quiet", "origin", "HEAD:main", cwd=tmp, check=False).returncode:
            run("fetch", "--quiet", "origin", cwd=tmp)
            run("rebase", "--quiet", "origin/main", cwd=tmp)  # one local, unpushed commit
            run("push", "--quiet", "origin", "HEAD:main", cwd=tmp)
        return run("rev-parse", "HEAD", cwd=tmp).stdout.strip()
    finally:
        run("worktree", "remove", "--force", str(tmp), cwd=root, check=False)


def read_record(root, rev, ref):
    text = git(root, "show", f"{rev}:{record_path(ref)}", check=False)
    if not text:
        return None
    try:
        rec = json.loads(text)
    except ValueError:
        return {"state": "?", "broken": True}
    return rec if isinstance(rec, dict) else {"state": "?", "broken": True}


def freshness(root, rev, record, ticket, plans):
    """(fresh, why): whether a recorded decision still holds on `rev`."""
    if record.get("broken") or record.get("state") not in STATES:
        return False, f"{record_path(ticket['ref'])} cannot be read"
    if record.get("fingerprint") != fingerprint(root, rev, ticket):
        return False, "the ticket, its leaf file or its epic file changed since"
    was, now = set(record.get("prereqs_done", [])), set(done_prereqs(ticket, plans))
    if was != now and not (record.get("state") == "ready-to-implement" and was <= now):
        return False, "a prerequisite was done since" if was <= now else "a prerequisite is no longer done"
    base = record.get("main_sha", "")
    if not base or git(root, "cat-file", "-e", f"{base}^{{commit}}", check=False) is None:
        return False, "the commit it was made on is unknown here"
    changed = (git(root, "diff", "--name-only", base, rev, check=False) or "").splitlines()
    hit = [p for p in changed if _touched(p, ticket.get("touches"))]
    if hit:
        more = f" and {len(hit) - 3} more" if len(hit) > 3 else ""
        return False, "main changed " + ", ".join(hit[:3]) + more
    return True, ""


def statuses(root, rev, tickets, plans):
    """{ref: {state, fresh, why, summary, rationale, questions, next_step, plan, triaged_at}} for every ticket
    with a decision.
    Cached per commit: the answer depends on nothing else."""
    sha = (git(root, "rev-parse", "--verify", "--quiet", rev, check=False) or "").strip()
    key = (str(root), sha)
    if sha and key in _cache:
        return _cache[key]
    out = {}
    for t in tickets:
        rec = read_record(root, rev, t["ref"])
        if rec is None:
            continue
        fresh, why = freshness(root, rev, rec, t, plans)
        out[t["ref"]] = {"state": rec.get("state"), "fresh": fresh, "why": why, "summary": rec.get("summary", ""),
                         "rationale": rec.get("rationale", []), "questions": rec.get("questions", []),
                         "next_step": rec.get("next_step", ""), "plan": rec.get("plan"),
                         "triaged_at": rec.get("triaged_at", ""),
                         "prepared": prepared(root, rev, t, rec, fresh)}
    if sha:
        _cache.clear()
        _cache[key] = out
    return out


def _load(root, rev, ref):
    files = board.bmad_files(root, rev)
    problems = []
    tickets = board.read_tickets(files, problems)
    plans = board.read_plans(files)
    ticket = next((t for t in tickets if t["ref"] == ref), None)
    if ticket is None:
        raise SystemExit(f"triage: no ticket {ref} in the tickets.toml files on {rev}")
    return ticket, plans


def main(argv=None):
    ap = argparse.ArgumentParser(description="Record a ticket's triage decision, or check whether it holds.")
    ap.add_argument("ref")
    ap.add_argument("--root", default=".")
    ap.add_argument("--rev", default="origin/main", help="where tickets and decisions are read (default origin/main)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="none | fresh <state> | stale <state>: <why>")
    r = sub.add_parser("record", help="check a decision and write docs/triage/<ref>.json here")
    r.add_argument("decision", help="a file with the triage skill's JSON answer")
    r.add_argument("--push", action="store_true",
                   help="fetch, then commit the decision straight onto main instead of writing it here")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    push = args.cmd == "record" and args.push
    if push:
        if args.rev != "origin/main":
            print("refused: --push records against origin/main; leave out --rev")
            return 1
        git(args.root, "fetch", "--quiet", "origin")
    ticket, plans = _load(args.root, args.rev, args.ref)

    if args.cmd == "check":
        rec = read_record(args.root, args.rev, args.ref)
        if rec is None:
            print("none")
            print(f"no decision for {args.ref} on {args.rev}: triage it")
            return 0
        fresh, why = freshness(args.root, args.rev, rec, ticket, plans)
        if not fresh:
            print(f"stale {rec.get('state')}: {why}")
            return 0
        print(f"fresh {rec['state']}")
        leaf = prepared(args.root, args.rev, ticket, rec, fresh)
        if leaf:
            print(f"prepared: {leaf}")
        elif rec["state"] == "ready-to-implement":
            print(f"plan: {'the lap approves it' if rec.get('plan') == 'lap' else 'a human approves it'}")
        print(rec.get("summary", ""))
        for q in rec.get("questions", []):
            print(f"- {q}")
        return 0

    try:
        decision = parse_decision(Path(args.decision).read_text(encoding="utf-8"))
        if decision is None:
            raise ValueError(f"no JSON object with a `state` in {args.decision}")
        rec = build_record(decision, args.root, args.rev, ticket, plans)
    except (OSError, ValueError) as e:
        print(f"refused: {e}")
        return 1
    if push:
        try:
            sha = commit_to_main(args.root, f"triage-{args.ref}-", lambda tmp: write_record(tmp, rec), RECORD_DIR,
                                 f"Triage ticket {args.ref}: {rec['state']}\n\nRecorded with triage.py record --push.")
        except RuntimeError as e:
            print(f"refused: could not push to main: {e}")
            return 1
        if sha is None:
            print(f"unchanged: main already has this decision for {args.ref} ({record_path(args.ref)})")
        else:
            print(f"recorded {rec['state']} for {args.ref} on main at {sha[:7]}: {record_path(args.ref)}")
        return 0
    path = write_record(args.root, rec)
    print(f"recorded {rec['state']} for {args.ref} at {rec['main_sha'][:7]}: {path}")
    print("Commit it to main; until then nothing reads it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
