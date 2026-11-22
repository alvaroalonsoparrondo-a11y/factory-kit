#!/usr/bin/env python3
"""The lap's round budget: one count for every fix that is checked again. Human-owned.

Part of the judge. Standard library only (Python 3.11+). The lap agent may run `take` and
`status`; `grant` is the human's (the fence denies it to the agent).

  python harness/board/lap_round.py <ref> take <source> "<finding>"
  python harness/board/lap_round.py <ref> status
  python harness/board/lap_round.py <ref> grant <n> "<why>"

A round is a fix that is checked again: a review loopback, a red gate fixed and run again, a failed
runtime check, a red check on the pull request, a merge of main that needed conflicts resolved.
The sources and the budget (default 3 per lap, every source together) are in `harness/rounds.json`.
Not a round: the first run of a check, a clean merge of main, and any failure of the machine
rather than the change (a usage limit, a check that could not start, a lost network). Those
never take a round; the lap signals `waiting manual-step` instead.

`take` exits 0 and records the round. It refuses, and itself records the lap as waiting, so the
board and the dispatcher see the stop even if nobody reads the output:
- exit 3 when the budget is spent: every finding so far is printed for the human;
- exit 4 when the same source reports the same finding as the round before: the last fix did
  not fix it, and repeating it would spend the budget one symptom at a time.

The record is `.lap/<ref>.jsonl`, the same file `lap_signal.py` writes, so the live board and the
dispatcher read rounds with the lap's other signals. A `release` in the dispatcher does not reset
it: only a human's `grant` adds rounds.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lap_signal  # noqa: E402

CONFIG = json.loads((HERE.parent / "rounds.json").read_text(encoding="utf-8"))
BUDGET = int(CONFIG["budget"])
SOURCES = tuple(CONFIG["sources"])
SPENT, REPEATED = 3, 4


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def summary(events, budget=BUDGET):
    """{used, budget, left, by_source, rounds} from a lap's signals (any order of other signals)."""
    rounds = [e for e in events if e.get("state") == "round"]
    granted = sum(int(e.get("n", 0)) for e in events if e.get("state") == "grant")
    total = budget + granted
    by_source = {}
    for r in rounds:
        by_source[r.get("source", "?")] = by_source.get(r.get("source", "?"), 0) + 1
    return {"used": len(rounds), "budget": total, "left": max(total - len(rounds), 0),
            "by_source": by_source, "rounds": rounds}


def text_of(s):
    """`2 of 3 (review 1, gates 1)`."""
    parts = ", ".join(f"{k} {v}" for k, v in s["by_source"].items())
    return f"{s['used']} of {s['budget']}" + (f" ({parts})" if parts else "")


def read(root, ref):
    path = Path(root) / ".lap" / f"{ref}.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict):
            events.append(e)
    return events


def _append(root, ref, line):
    folder = Path(root) / ".lap"
    folder.mkdir(exist_ok=True)
    with open(folder / f"{ref}.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _now(now=None):
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def take(root, ref, source, finding, now=None):
    """(exit code, message). Records the round, or the stop that refuses it."""
    if not lap_signal.REF.fullmatch(ref or "") or ".." in ref:
        raise ValueError(f"not a ticket ref: {ref!r}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}, not {source!r}")
    finding = " ".join((finding or "").split())
    if not finding:
        raise ValueError("say what the check found")
    events = read(root, ref)
    s = summary(events)
    if s["left"] == 0:
        found = "; ".join(f"{r.get('source')}: {r.get('text')}" for r in s["rounds"])
        why = f"round budget spent ({text_of(s)}); now {source}: {finding}"
        lap_signal.record(root, ref, "waiting", "limit", why, now)
        return SPENT, (f"No round left: {text_of(s)}. Stop the lap. Findings so far: {found}; now {source}: "
                       f"{finding}. The product owner splits or rewrites the ticket, or a human grants a round.")
    # A human's grant after that round lets the lap try the same finding once more.
    last_grant = max((i for i, e in enumerate(events) if e.get("state") == "grant"), default=-1)
    previous = [i for i, e in enumerate(events) if e.get("state") == "round" and e.get("source") == source]
    if previous and previous[-1] > last_grant and _norm(events[previous[-1]].get("text")) == _norm(finding):
        why = f"{source} found the same thing again after a round that fixed it: {finding}"
        lap_signal.record(root, ref, "waiting", "decision", why, now)
        return REPEATED, (f"The same {source} finding came back after the round that was to fix it. Stop: the fix "
                          "did not reach the cause. A human decides whether the lap gets another round.")
    n = s["used"] + 1
    _append(root, ref, {"at": _now(now), "state": "round", "source": source, "text": finding, "n": n})
    return 0, f"Round {n} of {s['budget']} ({source}). Fix the whole class of this finding in this round, not one instance."


def grant(root, ref, n, why, now=None):
    if n < 1:
        raise ValueError("grant at least 1 round")
    if not (why or "").strip():
        raise ValueError("say why the lap gets more rounds")
    _append(root, ref, {"at": _now(now), "state": "grant", "n": n, "text": " ".join(why.split())})
    lap_signal.record(root, ref, "working", now=now)
    return f"Granted {n} round(s): {text_of(summary(read(root, ref)))}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="The lap's round budget.")
    ap.add_argument("ref")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("take", help="before a fix that will be checked again")
    t.add_argument("source", choices=SOURCES)
    t.add_argument("finding")
    sub.add_parser("status", help="rounds used and left")
    g = sub.add_parser("grant", help="a human gives the lap more rounds")
    g.add_argument("n", type=int)
    g.add_argument("why")
    a = ap.parse_args(argv)
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                              check=True).stdout.strip()
        if a.cmd == "take":
            code, message = take(root, a.ref, a.source, a.finding)
            print(f"lap {a.ref}: {message}")
            return code
        if a.cmd == "grant":
            print(f"lap {a.ref}: {grant(root, a.ref, a.n, a.why)}")
            return 0
        print(f"lap {a.ref}: rounds {text_of(summary(read(root, a.ref)))}")
        return 0
    except subprocess.CalledProcessError:
        print("lap_round: not inside a Git repository", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"lap_round: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
