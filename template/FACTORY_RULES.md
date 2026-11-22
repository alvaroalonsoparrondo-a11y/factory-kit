# Factory rules

> **Written and changed by a human only.**

## 1. Irreversible actions stop the lap

The agent does not implement any of the following. It stops, says which rule applies, and waits for a human decision.

- Identity, login, sessions, passwords, tokens, roles or permissions.
- Database migrations, and any change that deletes or rewrites stored data.
- Secrets, keys, certificates, or anything that sends data to a new outside party.
- Deployment, release, or infrastructure changes.

A human may approve one such change by adding the label `human-approved-irreversible` to the pull request in the browser.

## 2. The judge belongs to humans

This rule applies in projects made from the kit. It does not apply in `factory-kit` itself.

The agent never creates, edits, moves or deletes these paths:

- `MISSION.md`, `FACTORY_RULES.md`, `AGENTS.md`, `CLAUDE.md`, `kit.lock.json`
- `harness/`
- `.github/`
- `.claude/settings.json`, `.claude/skills/lap/`
- `.kiro/agents/`, `.kiro/skills/lap/`
- `_bmad/custom/`

If a ticket seems to need such a change, the agent stops and asks. A human may approve one by adding the label `human-judge-change` to the pull request.

## 3. Tests are evidence, not obstacles

- Never delete, skip, disable or weaken a test to make a build green.
- A changed assertion must be explained in the pull request, with the requirement that justifies it.
- New behaviour comes with a test that fails without it.

## 4. Evidence comes from CI

"It passes on my machine" is not evidence. A lap is done when the required checks on the pull request are green: `gates`, `protected-paths`, `scope-guard`.

## 5. One ticket per lap

One ticket, one branch (`story/<id>`), one pull request. No extra features, no drive-by refactoring, no new dependencies unless the ticket names them.
