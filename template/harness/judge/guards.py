#!/usr/bin/env python3
"""The two guard checks, `protected-paths` and `scope-guard`, in one place. Human-owned.

Part of the judge. Standard library only (Python 3.11+). The patterns live in guards.json.
Both `.github/workflows/judge-guards.yml` and the factory judge (`judge.py`, for hosts
without GitHub Actions) call this, so the two can never judge differently.

  python harness/judge/guards.py <check> [--labels a,b] [--template] < changed-files

Reads the pull request's changed files, one per line (for `protected-paths`, include each
rename's previous name too), prints what it found and exits 0 (pass) or 1 (fail).
It reads file names only: it never runs or opens pull request code.
"""
import argparse
import json
import re
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent / "guards.json").read_text(encoding="utf-8"))
CHECKS = tuple(RULES)


def names(files, check):
    """File names to judge from the pull request files API (dicts) or plain names (strings)."""
    out = []
    for f in files:
        if isinstance(f, str):
            out.append(f)
            continue
        out.append(f["filename"])
        if RULES[check]["renames"] and f.get("previous_filename"):
            out.append(f["previous_filename"])
    return [n for n in out if n]


def judge(check, files, labels=(), template=False):
    """(passed, hits, message) for one guard on one pull request."""
    rule = RULES[check]
    if template and rule["skip_template"]:
        return True, [], "Skipped: the template repository (the kit) is not judged by this check."
    regex = re.compile(rule["pattern"], re.I if rule["ignore_case"] else 0)
    hits = sorted({n for n in names(files, check) if regex.search(n)})
    if not hits:
        return True, [], f"No {check} hit in the changed paths."
    if rule["label"] in labels:
        return True, hits, f"{rule['found']}; allowed by label {rule['label']}."
    return False, hits, f"{rule['found']}. A human must add the label {rule['label']} to allow this."


def description(passed, hits, message, limit=140):
    """A commit status description (GitHub allows 140 characters)."""
    text = message if passed or not hits else f"{len(hits)} hit(s): {', '.join(hits)}. Needs a human label."
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("check", choices=CHECKS)
    p.add_argument("--labels", default="", help="the pull request's labels, comma-separated")
    p.add_argument("--template", action="store_true", help="the repository is a template (the kit)")
    a = p.parse_args(argv)
    files = [line.strip() for line in sys.stdin if line.strip()]
    labels = [label for label in a.labels.split(",") if label]
    passed, hits, message = judge(a.check, files, labels, a.template)
    if hits:
        print(RULES[a.check]["found"] + ":")
        print("\n".join(hits))
    print(message)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
