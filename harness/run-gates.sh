#!/usr/bin/env bash
# The three gates. CI runs exactly this script. Human-owned: see harness/README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

CANDIDATE="${FACTORY_RUNTIME_CANDIDATE:-$(git rev-parse HEAD 2>/dev/null || echo uncommitted)-local}"
PORT="${PORT:-8080}"
BASE="http://localhost:${PORT}"

if [ ! -f backend/pom.xml ]; then
  if [ -f harness/skeleton.lock ]; then
    echo "GATE FAIL: backend/pom.xml is missing after the walking skeleton was locked."
    exit 1
  fi
  echo "NOTICE: no backend yet, nothing to judge."
  exit 0
fi

echo "== Gate 1: frontend static + unit =="
if [ -f frontend/package.json ]; then
  (cd frontend && npm ci && npm run lint && npm test -- --watch=false && npm run build)
else
  echo "NOTICE: no frontend yet."
fi

echo "== Gate 1 + 2: backend static, unit, contract =="
mvn -B -f backend/pom.xml verify

echo "== Gate 3: end-to-end on a fresh application =="
JAR="$(ls backend/target/*.jar | grep -v -e '-plain' -e '-sources' -e '-javadoc' | head -n 1)"
[ -n "$JAR" ] || { echo "GATE FAIL: no runnable jar in backend/target/"; exit 1; }

DATA="$(mktemp -d)"
FACTORY_RUNTIME_CANDIDATE="$CANDIDATE" APP_DATA_DIR="$DATA" \
  java -jar "$JAR" --server.port="$PORT" > "$DATA/app.log" 2>&1 &
APP_PID=$!
trap 'kill "$APP_PID" 2>/dev/null || true' EXIT

ready=""
for _ in $(seq 1 60); do
  if curl -fsS "$BASE/actuator/health" > /dev/null 2>&1; then ready=1; break; fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then break; fi
  sleep 2
done
if [ -z "$ready" ]; then
  echo "GATE FAIL: application did not become healthy. Last log lines:"
  tail -n 40 "$DATA/app.log" || true
  exit 1
fi

SEEN="$(curl -fsS "$BASE/build-id" | tr -d '\r\n')"
if [ "$SEEN" != "$CANDIDATE" ]; then
  echo "GATE FAIL: build identity mismatch. expected=$CANDIDATE seen=$SEEN"
  exit 1
fi
echo "candidate under test: $SEEN"

if [ -f e2e/package.json ]; then
  (cd e2e && npm ci && npx playwright install chromium && BASE_URL="$BASE" npx playwright test)
else
  echo "NOTICE: no e2e journeys yet."
fi

echo "GATES PASSED for $CANDIDATE"
