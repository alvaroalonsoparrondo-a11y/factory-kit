## Ticket

<!-- id and title -->

## What changed

<!-- two or three sentences -->

## Evidence

- Local gates: <!-- PASSED / FAILED --> — candidate `<!-- id printed by harness/run-gates.sh -->`
- Runtime verification: <!-- paste `python harness/runtime/verify.py <ticket-id> summary`: verified / skipped (why) -->
- Rounds used: <!-- `python harness/board/lap_round.py <ticket-id> status`, e.g. 1 of 3 (review 1) -->

The evidence that counts is the required checks below this pull request: `gates`, `protected-paths`, `scope-guard`.

## Assumptions on open questions

<!-- each open question from MISSION.md that this change relied on, and the default used; or "none" -->

## Deferred or risky

<!-- anything left out, or "none" -->
