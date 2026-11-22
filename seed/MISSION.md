# Mission

> **Written and changed by a human only.** The agent reads this file in every session and may not edit it.
> Fill it in from the PRD after the product-manager session (`bmad-agent-pm`), before the backlog is sliced.

## Product

_One paragraph: what this product is, who uses it, and the one outcome it exists for._

## In scope

- _…_

## Out of scope

- _Things the agent must not build, even if a ticket seems to ask for them._

## Hard invariants

Rules that must hold after every change. A change that breaks one is rejected, whatever else it does.

1. _Example: every API response for an unknown id is 404 with the standard error body._
2. _…_

## Open questions

Questions nobody has answered yet. The agent may proceed on the stated default and must list the assumption in the pull request.

| # | Question | Default until answered |
|---|---|---|
| Q1 | _…_ | _…_ |

## Decisions

Answered questions move here, with the date. They are not asked again.

| Date | Decision |
|---|---|

## Decisions that stay with a human

- Anything listed in `FACTORY_RULES.md`.
- Any change to this file, to `harness/`, to `.github/`, or to the factory's own configuration.
- _…_
