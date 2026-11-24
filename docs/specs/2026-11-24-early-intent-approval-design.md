# Early intent approval — design

Date: 2026-11-24. Status: proposed. Seen in `factory-pilot-2`.

## Why

Today the human reviews a lap's plan while the lap is running: `bmad-build` stops at CHECKPOINT 1 and waits. Triage (factory-kit#31) lets the lap approve its own plan for a small, clear ticket, but any ticket that needs a human's decision still stops the lap halfway.

The goal: **the human is never asked anything during a lap.** What needs the human, the "what" of a ticket, is settled before the lap starts, in planning time, while another lap runs. The "how" (Code Map, tasks) stays with the lap, which writes it against the code as it is when the lap starts.

## Goals

- A ticket whose "what" the human approved ahead runs its whole lap without a question to the human.
- The human prepares ticket N+1 while ticket N's lap runs.
- One place holds the approved "what": the ticket.

## Non-goals

- Writing plans (Code Map, tasks) ahead of the lap. They go stale when the ticket before merges.
- Changing the "what" during a lap.
- Changing anything for a ticket that was not prepared ahead.

## Anti-goals

- A prepared lap that still stops to wait for the human. That is the failure this design exists to remove.
- Two documents holding the "what" that can disagree (ticket and plan).

## Approaches considered

- **A. The "what" lives in the ticket (chosen).** The human approves the ticket's criteria with the product owner (Sofia's refine). The lap copies them into the plan's locked section. Editing the ticket already makes triage stale, so the factory notices a change on its own.
- **B. The "what" lives in an early plan.** A `draft` plan on `main` holds the locked section, which `bmad-build` keeps word for word. Rejected: plans on `main` before any lap, and a second document beside the ticket that can disagree with it.
- **Reviewing the plan during the lap** (today): what this removes for prepared tickets.

## Design

### 1. Preparing a ticket (before the lap)

- Triage sends a ticket to the human (`ready-to-spec` or `needs-info`), or the human picks one to prepare.
- The human refines it with Sofia (`refine <ref>`). The ticket's leaf file gets numbered Given/When/Then criteria, Boundaries, and `refined: true`. **`refined: true` is the human's approval of the "what".**
- The change to the ticket makes the triage decision stale; the ticket is triaged again.

**A ticket is prepared when** its leaf file has `refined: true` and its triage is a fresh `ready-to-implement`. Nothing else counts.

### 2. A prepared lap never waits

- The lap copies the ticket's criteria and Boundaries into the plan's locked section (`<frozen-after-approval>`) as they are, then writes Intent, Code Map and tasks around them.
- At CHECKPOINT 1 the lap approves its own plan, for every prepared ticket, whatever its `risk`. The risk was weighed when the human approved the ticket.
- The approval is written in the plan's commit message: `Plan approved by prepared ticket (<leaf file>)`.

### 3. When the plan needs the human anyway: hand back, never wait

If a prepared lap's plan comes out with an `## Open Questions` entry, or `bmad-build` finds an intent gap later, the lap does not ask. It:

1. marks the ticket blocked with the questions (`tickets.py mark <ref> draft --blocked "<questions>"`), on `main`;
2. deletes its branch on `origin` and ends, with no pull request;
3. reports one line: the ticket was handed back, and why.

The ticket shows under Needs you on the live dashboard. The human answers in the next planning slot by editing the ticket, which makes triage stale and lets the ticket be triaged and built again. The cost is one partial lap, never the human's attention mid-lap.

A dispatched lap does the same; the dispatcher already shows a blocked ticket under Needs you and does not claim it again until it is unblocked.

### 4. A ticket that was not prepared: unchanged

Without `refined: true`, the lap behaves exactly as today: triage's rules apply (a fresh `ready-to-implement` without `risk = "high"` or `hitl = true` lets the lap approve a plan with no open questions), and otherwise CHECKPOINT 1 waits for the human. Hand-back does not apply.

### 5. Changing the "what"

Edit the ticket before the lap, or after it ends. To change it during a lap, stop the lap. The lap reads the ticket once, at its start.

## What changes in the kit

- **Lap skill**, step 3: say whether the ticket is prepared (leaf file `refined: true` and fresh `ready-to-implement`). Step 6: for a prepared ticket, copy the criteria into the locked section, self-approve, and hand back on an open question or intent gap (section 3). Everything else as today.
- **`_bmad/custom/bmad-build.toml`**: for a prepared ticket, CHECKPOINT 1 is approved by the lap, and an open question or intent gap halts back to the lap instead of asking.
- **`triage.py`** (or a small helper next to it): a `prepared` answer, so the lap and the dispatcher read it the same way.
- **No board or dashboard changes.** A handed-back ticket already shows its questions under Needs you on the live dashboard, through its blocked reason. (The CI board is to be removed; the live dashboard stays.)
- **RUNBOOK**: a short "Prepare the next ticket while a lap runs" section.

## Left to the builder

- Where `prepared` is computed (in `triage.py` or the lap skill) and its exact output.
- The wording of the hand-back line.
- Tests: a prepared ticket self-approves regardless of risk; an unprepared ticket keeps today's behavior; an open question on a prepared lap hands back instead of waiting.

## Calls made in this design (check these)

- `refined: true` on the ticket's leaf file is the approval signal. A ticket without a leaf file is never prepared.
- A prepared ticket self-approves even with `risk = "high"`. `hitl = true` tickets: also self-approve the plan, since `hitl` means a person does part of the work, not that the plan needs review.
- "Unchanged" for unprepared tickets means today's behavior on factory-kit `main`, including triage's existing self-approval for clear, low-risk tickets.
