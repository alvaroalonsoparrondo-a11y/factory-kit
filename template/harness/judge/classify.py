#!/usr/bin/env python3
"""Why the gates are red: the change, `main`, or the machine. Human-owned.

Part of the judge. Standard library only (Python 3.11+). After `archon-validate`'s classify step.

  python harness/judge/classify.py <gates log> [--check-main] [--port 8190]

Prints one word on the first line, then the evidence:

- `environment`: the machine failed, not the change. A known machine failure is in the failing
  gate's part of the log: a download or network error, a port in use, a missing tool, a full disk, a
  browser that could not be installed. No round: fix the machine and run again.
- `inherited` (only with `--check-main`): the gates are red on `origin/main` alone, too, so the
  change did not cause it. No round: `main` needs a fix first.
- `introduced`: anything else. The conservative default: without evidence of the machine or of
  `main`, the change is assumed to have caused it. This takes a round.
- `timeout`: the gates did not finish in time. No round on its own: it may be the machine.

A machine failure needs positive evidence, a line that matches below; an unknown failure is never
called `environment`. Only the failing gate counts: `run-gates.sh` stops at the first red step, so
that is the part of the log after the last `== Gate` heading. A machine line in an earlier gate came
from a step that recovered. And a failure the change can cause (a failing test, a compile error) in
the failing gate makes it `introduced` even beside a machine line, so one stray line cannot dodge
the round budget. Green comes from the exit code alone, never from this script.
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Each pattern names one kind of machine failure. Keep them narrow: a match takes no round, so a
# pattern that also matches a failure the change can cause lets the change escape the budget.
# Not here on purpose: ECONNREFUSED (the app under test may have crashed), test failures, compile
# errors, assertion messages.
ENVIRONMENT = [
    ("network", r"\bE(CONNRESET|TIMEDOUT|NOTFOUND|AI_AGAIN|NETUNREACH)\b"),
    ("network", r"npm ERR! network"),
    ("network", r"Could not transfer artifact .* from/to "),
    ("network", r"\b(UnknownHostException|NoRouteToHostException)\b"),
    ("network", r"Temporary failure in name resolution"),
    ("network", r"\bConnect(ion)? timed out\b"),
    ("port", r"Address already in use"),
    ("port", r"Port \d+ (is|was) already in use"),
    ("tool", r"\b(java|mvn|npm|npx|node|git|bash|curl): (command )?not found\b"),
    ("tool", r"JAVA_HOME is not (defined|set) correctly"),
    ("tool", r"Windows Subsystem for Linux has no installed distributions"),  # WSL's bash, not Git's
    ("disk", r"No space left on device"),
    ("browser", r"Failed to (download|install) (browser|chromium|Chromium)"),
    ("browser", r"Host system is missing dependencies to run browsers"),
]
# Failures the change can cause, with evidence the code ran and was wrong. Beside a machine line
# they win, so they may be broad: a match here only ever takes a round. Not here on purpose: the
# harness's own `GATE FAIL:` lines (a port in use can stop the app becoming healthy) and test
# *errors* (a test that could not start, e.g. on a port in use), which stay neutral.
CHANGE = [
    ("tests", r"Tests run: \d+, Failures: [1-9]"),                   # Maven Surefire / Failsafe summary
    ("tests", r"^\[ERROR\]\s+[\w.$]+:\d+ "),                         # a failing test: Class.method:line message
    ("tests", r"^\s*\d+ failed\b"),                                   # Playwright
    ("tests", r"\bTests?\s+\d+ failed\b"),                            # Vitest / Jest summary
    ("compile", r"COMPILATION ERROR"),
    ("compile", r"\.java:\[\d+,\d+\]"),                                 # javac, as Maven prints it
    ("compile", r"\berror TS\d+:"),
    ("lint", r"\u2716 \d+ problems?\b"),                                # ESLint
]
TIMEOUT = "GATE STOPPED: did not finish"
SECTION = re.compile(r"^== Gate\b.*$", re.MULTILINE)


def failing_gate(text):
    """The part of a gates log that belongs to the gate that failed: after the last `== Gate` heading."""
    heads = list(SECTION.finditer(text))
    return text[heads[-1].start():] if heads else text


def first_match(text, patterns):
    """(kind, line) for the first line of `text` that matches one of `patterns`, or None."""
    for line in text.splitlines():
        for kind, pattern in patterns:
            if re.search(pattern, line):
                return kind, line.strip()[:300]
    return None


def environment(text):
    """(kind, line) for a machine failure that explains a red gates log, or None.

    The machine line must be in the failing gate, and that gate must show no failure the change can cause."""
    gate = failing_gate(text)
    if first_match(gate, CHANGE):
        return None
    return first_match(gate, ENVIRONMENT)


def classify(text, main_red=None):
    """(cause, evidence). `main_red` is whether the gates are red on `main` alone (None: not checked)."""
    if TIMEOUT in text:
        return "timeout", "the gates did not finish in time"
    env = environment(text)
    if env:
        return "environment", f"{env[0]}: {env[1]}"
    if main_red:
        return "inherited", "the gates are red on main alone, too"
    gate = failing_gate(text)
    change, machine = first_match(gate, CHANGE), first_match(gate, ENVIRONMENT)
    why = (f"{change[0]}: {change[1]}" + (f" (beside a machine line, {machine[0]}: {machine[1]})" if machine else "")
           if change else "no machine failure in the failing gate")
    return "introduced", why + ("" if main_red is None else ", and main alone is green")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("log", help="the output of a red `harness/run-gates.sh`")
    p.add_argument("--check-main", action="store_true",
                   help="when no machine failure is found, run the gates on origin/main alone to see if it is red too")
    p.add_argument("--port", type=int, default=8190, help="the port for that run (default 8190)")
    a = p.parse_args(argv)
    text = Path(a.log).read_text(encoding="utf-8", errors="replace")
    main_red = None
    if a.check_main and not environment(text) and TIMEOUT not in text:
        import subprocess
        sys.path.insert(0, str(HERE))
        import judge  # noqa: E402  (its workspace: a worktree of origin/main, harness from main, no token)
        root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                                   check=True).stdout.strip())
        ws = judge.Workspace(root, root / ".factory" / "judge")
        sha = ws.fetch()
        path = ws.prepare(sha)
        log = ws.folder / "logs" / f"{sha[:12]}-main-check-gates.log"
        try:
            code, _ = ws.run(path, f"{sha}-classify", a.port, log, judge.DEFAULT_TIMEOUT_MINUTES * 60)
        finally:
            ws.cleanup(path)
        main_red = code is not None and code != 0 and not environment(log.read_text(encoding="utf-8", errors="replace"))
    cause, evidence = classify(text, main_red)
    print(cause)
    print(evidence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
