# Deliberate defects

One `*.patch` file per defect. To add one:

1. On a clean checkout of `main`, break the application in one small, realistic way (for example: return 200 where 404 is required).
2. `git diff > harness/mutations/<short-name>.patch`
3. `git checkout -- .`
4. Run `bash harness/calibrate.sh` and confirm the new defect is `CAUGHT`.

Good first defects: a wrong status code, a missing validation, an invariant from `MISSION.md` broken, data that survives a restart with a fresh `APP_DATA_DIR`, a `/build-id` that returns a fixed string.
