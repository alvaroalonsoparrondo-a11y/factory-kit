#!/usr/bin/env bash
# Run once, by a human, in a new project made from this template:
#   bash init-project.sh <github-owner> <project-name> [<github-host>]
# <github-host> is github.com unless the project lives on GitHub Enterprise (for example github.example.com).
# Fills in the placeholders, then removes itself.
set -euo pipefail
cd "$(dirname "$0")"
OWNER="${1:?usage: bash init-project.sh <github-owner> <project-name> [<github-host>]}"
PROJECT="${2:?usage: bash init-project.sh <github-owner> <project-name> [<github-host>]}"
HOST="${3:-github.com}"
PARENT="$(cd .. && pwd)"

files="$(grep -rlE '__OWNER__|__PROJECT__|__PARENT_DIR__|__HOST__' . \
  --exclude-dir=.git --exclude-dir=node_modules --exclude=init-project.sh \
  --exclude=README.md --exclude=MODIFYING.md --exclude=CHANGELOG.md --exclude=AGENT_SETUP.md || true)"
for f in $files; do
  sed -i "s#__PARENT_DIR__#${PARENT}#g; s#__PROJECT__#${PROJECT}#g; s#__OWNER__#${OWNER}#g; s#__HOST__#${HOST}#g" "$f"
  echo "filled in: $f"
done

# A project gets its own README; the kit-only documents go.
mv -- PROJECT_README.md README.md
rm -f -- AGENT_SETUP.md CHANGELOG.md
rm -rf -- docs/superpowers
rmdir -- docs 2>/dev/null || true
echo "replaced README.md; removed kit-only AGENT_SETUP.md, CHANGELOG.md and design documents"

rm -- init-project.sh
echo
echo "Done. Next: follow RUNBOOK.md, starting with 'Install BMAD'."
