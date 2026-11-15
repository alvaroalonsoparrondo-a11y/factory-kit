#!/usr/bin/env bash
# Calibrates the judge: every deliberate defect must turn the gates red.
# Human-owned: see harness/README.md. Needs a clean working tree.
set -uo pipefail
cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is not clean. Commit or stash first."
  exit 2
fi

shopt -s nullglob
patches=(harness/mutations/*.patch)
if [ ${#patches[@]} -eq 0 ]; then
  echo "NOTICE: no defects in harness/mutations/ yet. Nothing was calibrated."
  exit 0
fi

escaped=0
for p in "${patches[@]}"; do
  name="$(basename "$p" .patch)"
  if ! git apply --check "$p" 2>/dev/null; then
    echo "STALE    $name (patch no longer applies; a human must refresh it)"
    escaped=1
    continue
  fi
  git apply "$p"
  if bash harness/run-gates.sh > "/tmp/calibrate-$name.log" 2>&1; then
    echo "ESCAPED  $name (gates stayed green with this defect)"
    escaped=1
  else
    echo "CAUGHT   $name"
  fi
  git checkout -- . && git clean -fdq -- backend frontend e2e
done

exit "$escaped"
