#!/usr/bin/env python3
"""Records that a running lap waits for a human, or works again. The live board shows it.

Part of the judge. Human-owned: the lap agent may run it and may not change it.
Standard library only (Python 3.11+).

  python harness/board/lap_signal.py <ref> waiting <kind> "<what is needed>"
  python harness/board/lap_signal.py <ref> working

Each call adds one JSON line to `.lap/<ref>.jsonl` in the repository. Git ignores `.lap/`.
What it records is the agent's own word; it is never evidence about the work.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("permission", "choice", "approval", "question", "manual-step", "limit", "decision")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def record(root, ref, state, kind=None, text=None, now=None):
    """Append one signal to `<root>/.lap/<ref>.jsonl` and return it. Raises ValueError on bad input."""
    if not REF.fullmatch(ref or "") or ".." in ref:
        raise ValueError(f"not a ticket ref: {ref!r}")
    if state == "waiting":
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}, not {kind!r}")
        if not (text or "").strip():
            raise ValueError("say what is needed from the human")
    elif state == "working":
        if kind or text:
            raise ValueError("`working` takes no kind or text")
    else:
        raise ValueError(f"state must be `waiting` or `working`, not {state!r}")
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    line = {"at": at, "state": state}
    if state == "waiting":
        line.update(kind=kind, text=" ".join(text.split()))
    folder = Path(root) / ".lap"
    folder.mkdir(exist_ok=True)
    with open(folder / f"{ref}.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tell the live board that the lap waits for a human, or works again.")
    ap.add_argument("ref", help="the ticket's ref, for example 1.2")
    ap.add_argument("state", choices=("waiting", "working"))
    ap.add_argument("kind", nargs="?", help="with waiting: " + ", ".join(KINDS))
    ap.add_argument("text", nargs="?", help="with waiting: what is needed from the human")
    args = ap.parse_args(argv)
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                              check=True).stdout.strip()
        line = record(root, args.ref, args.state, args.kind, args.text)
    except subprocess.CalledProcessError:
        print("lap_signal: not inside a Git repository", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"lap_signal: {e}", file=sys.stderr)
        return 2
    print(f"lap {args.ref}: {line['state']}" + (f" ({line['kind']}): {line['text']}" if args.state == "waiting" else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
