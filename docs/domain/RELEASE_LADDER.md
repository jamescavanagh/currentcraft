---
title: Release ladder
version: 0.13.0
status: contracts and transition table implemented; authority verification, persistence and policy not implemented
tags: [currentcraft, domain, ladder, authority]
---

# Release ladder

> [!note] Status
> Implemented: the ladder contracts, transition table and replay in `app.application.ladder`, generated
> reference in [READINESS_CONTRACTS.md](../contracts/READINESS_CONTRACTS.md). Not implemented: verifying
> authority references or label events against identity and policy (0.15.0), persistence, and mapping process
> gate decisions onto ladder moves. Positive operational release stays fail-closed until an enterprise release
> policy has an approved owner. Not claimed: that reaching a rung authorizes anything outside this model.

## Purpose

A work package moves through **Possible -> Conditional -> Ready -> Executable**, or leaves through
**Returned**. The ladder makes the difference between work that might exist, work someone could do, work that
meets its prerequisites and work someone with authority has released visible and enforceable.

## Rules

1. **Growth only creates.** Grammar growth or intake creates work at `possible` and never moves existing work.
   Grammar growth cites its derivation.
2. **People move work.** Every move after creation is a human-in-the-loop move with a label event. Entering a
   gate is not approval.
3. **No skipping.** `release` moves exactly one rung up. `hold` never moves.
4. **Ready needs a computed reading.** Reaching `ready` needs a readiness reading that is computed (not
   simulated or unknown) with zero blocking criteria.
5. **Readiness is never release.** A readiness reading alone never reaches `executable`.
6. **Executable needs authority and evidence.** Reaching `executable` needs a release-scope authority reference,
   verification evidence and computed status. Simulated or unknown work never becomes executable.
7. **Returned records why.** `return` (disposition `rework`) and `reject` (disposition `rejected`) both need a
   reason. Reworked work may re-enter at `possible`; rejected work is terminal.
8. **Stable error codes.** Every refusal raises `LadderViolation` with a stable `code` for later API errors.

## Example

>>> from app.application.ladder import LadderMove, LadderViolation, ReadinessReading, apply_move
>>> grow = LadderMove(work_package_id="wp-1", verb="grow", origin="grammar_growth", derivation_id="drv-1")
>>> apply_move(None, grow)
'possible'
>>> reading = ReadinessReading(evaluation_id="ev-1", criteria_evaluated=3, blocking=0, epistemic_status="computed")
>>> to_ready = LadderMove(work_package_id="wp-1", verb="release", origin="hil", label_event_id="lbl-2",
...                       readiness=reading)
>>> apply_move("conditional", to_ready)
'ready'
>>> try:
...     apply_move("ready", to_ready)
... except LadderViolation as e:
...     print(e.code)
authority_missing

## Acceptance tests

`tests/test_release_ladder.py`: the full climb; growth never advances; HIL-only moves; readiness rules;
executable rules; no skipping; returns and terminal rejection; an exhaustive search over every sequence of up
to five non-authority moves showing `executable` is unreachable; a description on every field; this page's
example; slice layering.

## Limits

Authority references and label events are opaque strings here. Nothing in this slice checks who holds them.
