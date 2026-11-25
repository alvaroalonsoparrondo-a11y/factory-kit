# Copilot CLI alongside Claude Code and Kiro

Date: 2026-11-25.
Status: implementing supervised support; protected laps deferred by human decision.
Tracking issue: pending; github.com authentication returned HTTP 401.

## Goal and scope

Add Copilot CLI as an optional agent without changing Claude Code, Kiro or how
the kit is maintained. Reuse shared instructions and skills, not a third
workflow or a kit-maintenance skill.

The original proposal included interactive laps after a successful permission
check. That check failed, and the human selected **supervised-only**:
setup, BMAD planning and triage. Implementation and laps remain with Claude
Code or Kiro. Headless Copilot and cloud/IDE integration are out of scope.

## Compatibility evidence

Checked with Copilot CLI 1.0.115 on Windows in disposable local fixtures:

- CLI connectivity works; instruction discovery finds root `AGENTS.md` and
  `CLAUDE.md`.
- The existing `skills add ... -a claude-code --copy` commands install BMAD's
  core and method skills as real files in `.claude/skills/`. Copilot documents
  discovery there, so no Claude executable or third skill copy is needed.
- With `--sandbox`, a repository policy containing `readonlyPaths` still
  allowed both an ordinary Python write and a write to a protected fixture.
- `copilot config --repo sandbox.enabled true` explicitly rejects the setting:
  the repository cannot override it. The fixture policy therefore did not
  establish a native sandbox boundary.
- File-tool write rules do not cover shell commands. Hooks/manual approvals
  and disabled skills are not substitutes for filesystem protection.
- A trusted, no-write diagnostic session reported `lap`, `bmad-build` and
  `bmad-build-auto` unavailable, with `triage`, `bmad-agent-pm` and
  `bmad-agent-po` available. Untrusted CLI discovery still listed build skills
  as enabled, so setup distinguishes discovery from the trusted-session check.
- BMAD setup reported `6.13.0-next`, `current: true` and no problems. Factory
  customization resolution retained `factory-judge`, `thorough` and `MISSION.md`.

No live consumer, remote or credentials were used for write probes. No Linux
integration or complete Copilot lap is claimed.

## Implementation

1. Keep `AGENTS.md` authoritative and `CLAUDE.md` as its import. Explain
   Copilot's supervised-only boundary in the shared project instructions.
2. Share `.claude/skills/` with Claude Code, including Copilot-only setup.
   Keep Claude/Kiro skill copies unchanged and preserve setup's current
   default of those two agents.
3. Ship `.github/copilot/settings.json` with `lap`, `bmad-build` and
   `bmad-build-auto` in `disabledSkills`. Copilot supports repository-level
   disabled skills; Claude and Kiro do not consume this configuration.
   This is a workflow safeguard only, not a fence.
4. Have `kit.py doctor` statically validate that file, report malformed or
   missing settings, and reject configurations that omit the disabled skills.
   Do not require a live CLI or subscription in unit tests.
5. Update setup and runbook together: user-managed Copilot sign-in, discovery
   checks, manual permissions, individual approvals and a handoff to Claude
   Code/Kiro before implementation. Never broaden permissions automatically.

The new configuration is an ordinary kit-owned file under already-protected
`.github/`. Existing fences, guard patterns, `CODEOWNERS` and attributes already
cover that directory. No new fence format, lock schema, merge logic, judge or
dispatcher change is required.

## Validation and rollout

- Add focused doctor regressions for missing/malformed settings and enabled
  build skills, including case-insensitive names.
- Exercise an existing project's sync: it gains the configuration, retains
  project-owned local settings, and the next sync is a no-op.
- Run the kit and harness suites, and check live skill discovery in a
  disposable project. Keep evidence separate from claims of full lap support.
- Ship through the existing human-reviewed PR and human-run project sync.
  Existing projects' `/.github/` CODEOWNERS coverage already covers the file.

Root kit instructions and product lap/triage skill copies remain unchanged.
Do not install the factory into the kit itself. Any future protected Copilot
lap needs a separately approved and verified permission boundary.
