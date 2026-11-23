# Factory pilot

This repository is built one ticket at a time by an agent, planned with BMAD v7, and judged by CI that the agent cannot change.

These instructions are for any coding agent. Claude Code reads them through `CLAUDE.md`. Kiro CLI reads them directly and must run as the `factory` agent (`kiro-cli chat --agent factory`), because that agent carries the fence.

Before any work, read in full:

- `MISSION.md` — what the product is, what is out of scope, the hard invariants.
- `FACTORY_RULES.md` — what you must never do.
- `harness/README.md` — the runtime contract the application must keep so CI can start and check it.

How work is done here:

- Planning uses BMAD skills (`bmad-agent-pm`, `bmad-architecture`, `bmad-ux`, `bmad-agent-po`).
- Triage a ticket before its lap with the `triage` skill (`triage <ticket id>`). It only reads; `harness/board/triage.py` records its decision in `docs/triage/`, which a lap never changes.
- Building a ticket is always done through the `lap` skill. Do not implement a ticket any other way.
- Open pull requests with `gh` when the work calls for one (the `lap` skill opens its own). Never label, approve or merge a pull request; a human does that.
- Do not use `bmad-build-auto`.

Layout: `backend/` (Java 21, Spring Boot, Maven), `frontend/` (Angular), `e2e/` (Playwright), `harness/` (the judge; read-only for you).
