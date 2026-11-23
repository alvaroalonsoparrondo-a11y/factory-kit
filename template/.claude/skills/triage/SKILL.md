---
name: triage
description: 'Triages one BMAD ticket before its lap: reads the ticket, MISSION.md, the code on main and the board, and decides exactly one route (ready-to-implement, ready-to-spec, needs-info, wait). Read-only. Use when the user says "triage <ticket id>", "is <ticket id> ready to build", or when the factory dispatcher asks for a triage.'
---

# Triage

Decide how one ticket goes forward, before any lap starts it. The route is one of:

- `ready-to-implement`: a lap may build it, and approves its own plan when the plan has no open questions.
- `ready-to-spec`: the goal is right, but a human must settle the intent with the product owner first.
- `needs-info`: the ticket cannot be built or specified responsibly yet; name the questions.
- `wait`: not now (premature, conflicting, or out of the mission).

The goal is to route work honestly, not to make every ticket look ready. When the evidence sits between two routes, choose the more cautious one.

**Read-only.** Do not change any file, ticket, plan, branch or board state, and do not start a lap or a build. Your output is the decision; a script records it (step 6).

## 1. Identify the ticket

The ticket is a BMAD ticket ref such as `1.3`, named in the prompt. Find its entry in `_bmad-output/**/tickets/tickets.toml` (the `[[epic]]` table's `id` gives the epic number; the `[[entry]]`'s `id` the ticket number). If the prompt names no single ticket, ask; never guess. Headless (`FACTORY_DISPATCHED=1`), give `needs-info` with the question "which ticket?" instead.

## 2. Read the ticket and its context

Read, in full:

- `MISSION.md`: what the product is, what is out of scope, the hard invariants. It plays the part of a roadmap and vision.
- `FACTORY_RULES.md`, section 1 (irreversible actions) and section 2 (protected paths).
- The ticket's entry: `description`, `verify`, `covers`, `after`, `touches`, `risk`, `hitl`, `notes`, `references`.
- The ticket's leaf file, when the epic's `tickets/` folder has one whose frontmatter `id` is the entry's.
- The epic file (`epic-<slug>.md`): Outcome, Boundaries, `Done when`, Requirements lines the entry `covers`, and any `Decision:`, `Source conflict:` or `Open question` lines in Notes.
- The `references` the entry names (architecture decisions), only the sections it names.
- `docs/runtime/<ref>.json` when it exists: the scenario the lap will be judged by.

Then look at the neighbours:

- The tickets in the same `tickets.toml`: which are done (their plan's `status: done`), which are in flight (a `story/<ref>` branch), and which overlap this one's `touches` or `covers`.
- The ticket's `after` prerequisites: done, in flight, or not started.

Do not decide from the title alone.

## 3. Inspect the code

Read the code as it is on `main`. Search for the feature, the terms of the ticket and the paths in `touches`. Assess:

- Whether the behaviour exists already, in part or in full.
- The files and layers involved, and whether they match `touches`.
- Whether there is a bounded path for one lap (one agent session, three fix rounds).
- Existing patterns the change can follow, or the lack of one.
- Anything the ticket would need that `FACTORY_RULES.md` section 1 calls irreversible (identity, permissions, migrations, data deletion, secrets, deployment), or a protected path.
- Whether a prerequisite still in flight could change the answer.

Prefer targeted searches and reads. This is triage, not implementation.

## 4. Choose one route

### ready-to-implement

All of these hold:

- The behaviour and its acceptance are clear: `verify` (or the leaf file's criteria) says what a non-builder can check.
- The scope is bounded and fits the mission and the epic.
- The implementation area is identifiable, and the patterns to follow exist on `main`.
- A coding agent has a good chance of finishing it right in one lap.
- No product decision is open: the plan will not need to ask a human anything about intent.
- Every `after` prerequisite is done, or the open ones cannot change the intent (only where the code goes).
- Nothing in it is irreversible under `FACTORY_RULES.md` section 1.

### ready-to-spec

The goal is clear and fits the mission, and either:

- **Ambiguity:** two or more valid behaviours differ in what the user sees or what the API returns, and a human should choose (for example a value list, a status code, a message, an ordering); or
- **Complexity:** likely more than a few hundred lines, several layers that each need decisions, or real risk (`risk = "high"` on the entry usually lands here).

Name each decision to settle in `questions`, phrased for the product owner. The next step is refining the ticket with `bmad-agent-po` ("refine <ref>"), and architecture or UX on the epic when the question is theirs.

### needs-info

The problem, the expected behaviour or the acceptance is unclear, or a fact only a person has is missing. Give the smallest set of concrete questions whose answers would let triage run again.

### wait

- The ticket does not fit the mission or the epic's Boundaries, or the mission puts it out of scope.
- It duplicates or conflicts with another ticket, done or planned.
- It needs something irreversible (`FACTORY_RULES.md` section 1) that a human has not decided.
- A prerequisite or a strategic decision makes it premature.

Say what would have to change before it is worth triaging again. Do not choose `wait` only because the work is hard: hard but cohesive work is `ready-to-spec`.

## 5. Write the answer

Your final message is one raw JSON object, with no prose before or after it and no code fence:

{"ref": "<ticket ref>", "state": "ready-to-implement | ready-to-spec | needs-info | wait", "summary": "<one sentence: the decision and the main reason>", "rationale": ["<evidence, with file paths or ticket ids>", "..."], "questions": ["<for ready-to-spec and needs-info: each decision or question>"], "next_step": "<one concrete next step for the human or the lap>"}

- `questions` is empty for `ready-to-implement`, and must not be empty for `ready-to-spec` and `needs-info`.
- Keep `rationale` to the evidence that decided it: at most six short lines.
- No secrets, tokens, environment values or command output dumps.

## 6. Recording the decision

Headless (`FACTORY_DISPATCHED=1`): stop after step 5. The dispatcher records the decision.

By hand: after the answer, offer to record it. On yes, save the JSON object to `.lap/<ref>-triage.json` and run `python harness/board/triage.py <ref> record .lap/<ref>-triage.json`. It checks the decision, stamps it with `origin/main` and a fingerprint of the ticket, and writes `docs/triage/<ref>.json`. Show its output. The human commits that file to `main`; never commit or push it yourself.

A recorded decision goes stale when the ticket, its epic file or its prerequisites change, or when `main` changes a path in its `touches`; `triage.py <ref> check` says so, and the ticket is triaged again.
