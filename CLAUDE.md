# Factory pilot

This repository is built one ticket at a time by an agent, planned with BMAD v7, and judged by CI that the agent cannot change.

Before any work, read in full:

- `MISSION.md` — what the product is, what is out of scope, the hard invariants.
- `FACTORY_RULES.md` — what you must never do.
- `harness/README.md` — the runtime contract the application must keep so CI can start and check it.

How work is done here:

- Planning uses BMAD skills (`bmad-agent-pm`, `bmad-architecture`, `bmad-ux`, `bmad-agent-po`).
- Building a ticket is always done through the `lap` skill. Do not implement a ticket any other way.
- Do not use `gh`. Do not open, label, approve or merge pull requests. The human does that in the browser.
- Do not use `bmad-build-auto`.

Layout: `backend/` (Java 17, Spring Boot, Maven), `frontend/` (Angular), `e2e/` (Playwright), `harness/` (the judge; read-only for you).
