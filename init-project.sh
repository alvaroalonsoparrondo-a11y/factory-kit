#!/usr/bin/env bash
# Run once, by a human, in a new project made from this template:
#   bash init-project.sh <github-owner> <project-name>
# Fills in the placeholders, then removes itself.
set -euo pipefail
cd "$(dirname "$0")"
OWNER="${1:?usage: bash init-project.sh <github-owner> <project-name>}"
PROJECT="${2:?usage: bash init-project.sh <github-owner> <project-name>}"
PARENT="$(cd .. && pwd)"

files="$(grep -rlE '__OWNER__|__PROJECT__|__PARENT_DIR__' . \
  --exclude-dir=.git --exclude-dir=node_modules --exclude=init-project.sh \
  --exclude=README.md --exclude=MODIFYING.md --exclude=CHANGELOG.md --exclude=AGENT_SETUP.md || true)"
for f in $files; do
  sed -i "s#__PARENT_DIR__#${PARENT}#g; s#__PROJECT__#${PROJECT}#g; s#__OWNER__#${OWNER}#g" "$f"
  echo "filled in: $f"
done

# Switch the fence on. The kit itself runs without it; the fenced settings wait in fence/.
cp -- fence/claude-settings.json .claude/settings.json
cp -- fence/kiro-factory.json .kiro/agents/factory.json
rm -rf -- fence
echo "fence on: installed .claude/settings.json and .kiro/agents/factory.json from fence/"

# A project gets its own README; the kit-only documents go.
mv -- PROJECT_README.md README.md
rm -f -- AGENT_SETUP.md CHANGELOG.md
rm -rf -- docs/superpowers
rmdir -- docs 2>/dev/null || true
echo "replaced README.md; removed kit-only AGENT_SETUP.md, CHANGELOG.md and design documents"

rm -- init-project.sh
echo
echo "Done. Next: follow RUNBOOK.md, starting with 'Install BMAD'."
