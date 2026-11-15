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

1. **Static + unit:** frontend lint, unit tests and build; backend `verify`.
2. **Contract:** inside backend `verify` (see above).
3. **End-to-end on a fresh application:** start the jar with an empty `APP_DATA_DIR`, wait for health, check `/build-id` equals the candidate, run the Playwright journeys.

Until the walking skeleton exists there is nothing to judge and the script passes with a notice. After the skeleton merges, a human commits an empty file `harness/skeleton.lock`; from then on a missing backend is a failure.

## Calibration

`harness/mutations/` holds deliberate defects as patch files (`*.patch`, made with `git diff`). `harness/calibrate.sh` applies each one to a clean tree and expects the gates to go red. A defect that stays green has ESCAPED: a human adds the missing check. Add one patch for each kind of bug you want to be sure the gates catch.
