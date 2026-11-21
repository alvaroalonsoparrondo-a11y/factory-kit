# Harness: the judge

Everything in this folder is owned by humans. The agent may read it and run it, never change it.

## Runtime contract

CI can only judge an application it can start. The application must keep this contract from the first ticket (the walking skeleton) onward.

| Item | Contract |
|---|---|
| Backend build | `mvn -B -f backend/pom.xml verify` builds, lints and tests, and leaves exactly one runnable jar in `backend/target/` |
| Start command | `java -jar backend/target/<app>.jar --server.port=<port>` |
| Health | `GET /actuator/health` returns 200 when ready |
| Build identity | `GET /build-id` returns, as plain text, the value of the environment variable `FACTORY_RUNTIME_CANDIDATE` when it is set, otherwise the Git commit |
| State | All stored data lives under the directory named by `APP_DATA_DIR`. An empty directory means a fresh application. No other state. |
| Frontend | `frontend/` is an Angular project. `npm ci`, `npm run lint`, `npm test -- --watch=false` (headless) and `npm run build` all work. |
| Serving the UI | The backend jar serves the built frontend at `/`. The Maven build packages what `npm run build` left in `frontend/dist/`. |
| API contract | The API is described in `docs/openapi.yaml`. Backend tests check the running API against that file. |
| End-to-end | `e2e/` is a Playwright project. `npx playwright test` reads the application address from `BASE_URL`. |

## The gates

`harness/run-gates.sh` runs all three gates. CI runs exactly this script; you can run it locally too (Git Bash on Windows).

Where GitHub Actions is not allowed, the factory judge (`harness/judge/judge.py`) runs this same script on each pull request merged with `main`, and posts the result as the `gates` commit status. It also posts `protected-paths` and `scope-guard`, judged by `harness/judge/guards.py`, the same code `judge-guards.yml` runs. See `RUNBOOK.md`, "Without GitHub Actions".

1. **Static + unit:** frontend lint, unit tests and build; backend `verify`.
2. **Contract:** inside backend `verify` (see above).
3. **End-to-end on a fresh application:** start the jar with an empty `APP_DATA_DIR`, wait for health, check `/build-id` equals the candidate, run the Playwright journeys.

Until the walking skeleton exists there is nothing to judge and the script passes with a notice. After the skeleton merges, a human commits an empty file `harness/skeleton.lock`; from then on a missing backend is a failure.

## Calibration

`harness/mutations/` holds deliberate defects as patch files (`*.patch`, made with `git diff`). `harness/calibrate.sh` applies each one to a clean tree and expects the gates to go red. A defect that stays green has ESCAPED: a human adds the missing check. Add one patch for each kind of bug you want to be sure the gates catch.

## The round budget

`harness/rounds.json` holds the one budget every lap shares across all its checks: 3 rounds, a round being a fix that is checked again. `harness/board/lap_round.py` records and enforces it; the lap skill, `bmad-build`'s review loopbacks and the dispatcher all draw on it. See `RUNBOOK.md`, "The round budget".

`harness/judge/classify.py` says why red gates are red: `introduced` (a round), `environment` or `inherited` (no round), or `timeout`. The lap's local gates and the factory judge both ask it, so the agent never decides it. Its machine-failure patterns are kept narrow on purpose.

## Runtime verification

`harness/runtime/verify.py` starts the app as the runtime contract says (fresh `APP_DATA_DIR`, health, build identity), hands a context-free verifier `harness/runtime/verifier.md` with the ticket's scenario from `docs/runtime/<ref>.json` on `main`, and judges its report and evidence. See `RUNBOOK.md`, "Runtime verification".
