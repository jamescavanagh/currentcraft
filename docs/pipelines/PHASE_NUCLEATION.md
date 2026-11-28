---
title: Synthetic phase nucleation
version: 0.4.0
tags: [automl, simulation, graph, governance]
status: contracts, forward-dependency and predecessor-acceptance checks
---

# Synthetic phase nucleation

> [!note]
> Contracts, generated reference, forward-dependency and predecessor-acceptance checks and a synthetic two-subsystem fixture only (`app.application.phase`, schema `currentcraft-phase/v1`). No port, adapter, evaluator, model, live buffer, approval workflow or financial connector exists. Existing encoder interfaces remain ports only. No deployment, real records, or process-validity claims.

## Purpose

Let a reviewer trace a proposed handoff across two fictional subsystems: what was measured, what was inferred, what evidence the next phase requires, and who could accept or return the current revision. Keep measurements, graph proposals, authority, and commercial observations separate. See [docs-first design](../DOCS_FIRST.md) and [data policy](../../DATA_POLICY.md).

## Field to graph

1. Generate a pinned numerical velocity field. Record seed, time, grid, boundary, configuration, method, and tolerances. The tracer ring records simulated geometry; it is neither an event ring nor a process-domain `Buffer`.
2. Sample signed vorticity, absolute vorticity, speed, strain versus spin, dwell and dye. Apply a declared transform to selected columns, then fit standardization and PCA on training trajectories only when evaluating a model. The frozen two-dimensional projection is a viewing aid. Cluster in the standardized feature space and retain the original readings and coordinates. Report retained variance; do not interpret proximity as a dependency.
3. On the original field, locate candidate critical cells by winding and compare with the sign of the local velocity Jacobian determinant. A negative determinant indicates a saddle at a nondegenerate critical point. A positive determinant alone does not certify a vortex or stability. A traced lane or same-spin pair is a candidate, never a process edge. A feature-map Jacobian singular value measures local sensitivity, not a dynamical eigenvalue, Lyapunov exponent, or barrier certificate.
4. In a separate typed phase graph, map only declared synthetic evidence to capabilities (process plus resource), operands (objects, never people), declared buffers, phase revisions and acceptance checks. Keep geometry links, proposed process links and evidence-backed links separate. Use the [capability graph](HFGT_CAPABILITY_GRAPH.md) translation-gap and candidate-edge patterns; reuse the [probe](PROBE.md) label seam with the reading digest. A human label can resolve a candidate or register a disagreement. It cannot issue an acceptance decision. The [CNN/GNN ports](CNN_GNN_PIPELINE.md) may later rank candidates via typed inputs and array-free tensor references. Do not use post-decision features, including gate values influenced by the outcome.

## Phase boundary

```mermaid
flowchart LR
  P["Phase k: evidence submitted"] --> C["Evaluate published entry criteria for phase k+1"]
  C -->|"missing, failed or unknown"| R["Hold or return this revision"]
  C -->|"criteria satisfied"| D["Scoped human acceptance decision"]
  D -->|"accept"| N["Spawn phase k+1 as Possible"]
  A["Final accepted subsystem revisions"] --> I["Separate integration acceptance"]
  I -.-> B["Separate commercial evidence: invoice, receipt, reconciliation"]
```

The next phase's versioned entry criteria are available before the prior phase is accepted; no future execution or state is a prerequisite for that check. A `governs` edge points from that published check to the prior phase revision. It is not a forward scheduling dependency and never rewrites history. After a scoped human acceptance, a bounded rule can propose the next phase as `Possible`; a new phase is not automatically released. A later issue can open a new revision or exception without mutating the old acceptance. Forward `nucleates` and `requires_accepted` dependencies must be acyclic; check them separately from `governs` links and intra-phase rework.

Append transitions with deterministic replay. Repeating the same key and input digest is a no-op; a changed input under the same key is a conflict. Unknown, inaccessible, stale and failed evidence stay distinct. Neither readiness nor an accepted subsystem proves integration acceptance. Invoiced, received and reconciled are separate observations, not consequences the simulator can assert.

## Contracts

Generated reference: [phase contracts](../contracts/PHASE_CONTRACTS.md). Every validator traces to a rule below.

| Record | Contract | Required meaning |
| --- | --- | --- |
| Phase revision | `PhaseRevision` | Opaque phase, subsystem and revision IDs; entry-profile version and required predecessor revisions. |
| Reading or candidate | `PhaseReading` | Source and version, mapping and configuration digests, sample coordinates if synthetic, method, tolerances, validity and run reference. |
| Phase transition event | `PhaseTransitionEvent` | Prior and next state, phase revision, sequence, event and idempotency keys, input digest, transition-policy version, evidence and any required decision reference. |
| Acceptance decision | `AcceptanceDecision` | Exact revision, scope, authorized role, evidence references, rationale, decision time and any conditions or expiry. |
| Ledger observation | `LedgerObservation` | Offline fixture only: independent source revision, observation time and invoice, receipt or reconciliation status. No amounts, event writes or payment logic. |

Contract rules:

1. A revision is named `phase_id@revision_id`. It cannot require or nucleate itself; the revision that nucleated it must also be a required predecessor. Predecessor lists have no duplicates.
2. Allowed transitions: none → `possible`; `possible` → `conditional`; `conditional` → `ready` or back to `possible`; `ready` → `executing` or back to `conditional`; `executing` → `accepted` or back to `conditional`. `accepted` is absorbing for a fixed revision; a later issue opens a new revision.
3. Sequence 0 is the creating event and only it has no prior state.
4. The simulation trace never carries a decision reference. On the governance trace, entering `executing` or `accepted` requires a decision reference, and a governance acceptance must cite evidence.
5. An accept decision must cite evidence; expiry, if set, follows the decision time. A decision names a role, the record of its authority and the successor entry-check version it was evaluated against (the `governs` link). Only a human records a decision.
6. Readings carry validity `valid`, `stale`, `failed`, `unknown` or `inaccessible`; tolerances are named once and non-negative. Readings and ledger observations are synthetic in this alpha. Ledger observations carry no amounts.
7. Every timestamp is timezone-aware. Evidence, condition and reference lists have no duplicates.

Replay classification:

>>> from datetime import datetime, timezone
>>> from app.application.phase import PhaseTransitionEvent
>>> created = PhaseTransitionEvent(event_id="e1", idempotency_key="k1", phase_ref="design@r1", sequence=0,
...     prior_state=None, next_state="possible", input_digest="a" * 64, transition_policy_version="1",
...     trace="simulation", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
>>> created.replay_against(created)
'noop'
>>> created.replay_against(created.model_copy(update={"input_digest": "b" * 64}))
'conflict'

Contracts validate single records.

## Chain checks

`app.application.phase.graph` reads a set of revisions and checks forward dependencies only:

1. Forward edges run predecessor → successor and come only from `requires_accepted` (which always includes `nucleated_from`). A decision's `entry_check_ref` (the `governs` link) and intra-phase rework are not forward edges, so neither can close a cycle.
2. Duplicate revision references are rejected.
3. A forward cycle is rejected and reported as an explicit path, starting from the first revision in sorted order, so the report does not depend on input order.
4. A predecessor revision that is not in the set is returned as a `(successor, missing predecessor)` gap. It is never filled in, guessed or treated as acyclic evidence about the missing revision.
5. A new revision of an existing phase is a new node; it does not rewrite the old revision's edges.

The synthetic fixture `tests/fixtures/phase/two_subsystems.synthetic.json` has two subsystems with three phases each, one cross-subsystem dependency (`b.commission` requires `a.commission`), one simulated return for rework, one hold on stale evidence and one independent ledger observation.

## Predecessor acceptance

`app.application.phase.acceptance` reads revisions, decisions and events at an explicit, timezone-aware time:

1. A predecessor counts as `accepted` for a successor only through a human `AcceptanceDecision` on that exact revision, evaluated against that successor's published entry check (`entry_check_ref` equals the successor's `entry_profile_version`), decided at or before the reading time and not expired. Simulated transitions, labels and scores never count.
2. Statuses stay distinct: `accepted`, `held`, `returned`, `undecided`, `expired`, `conflict`, `other_entry_check` (accepted only against a different check) and `missing` (predecessor revision not in the set).
3. The latest relevant decision applies, except that `accepted` is absorbing for a fixed revision: a later hold or return on the same revision is a `conflict`, because a later issue needs a new revision. Different outcomes at the same decision time are also a `conflict`.
4. A revision is eligible to leave `possible` only when every required predecessor is `accepted`. Eligibility is a structural reading, not a release.
5. A governance event that leaves `possible` is read at its own `occurred_at`, so a later decision cannot backdate it. Simulation events are ignored. An event for a revision outside the set is reported as `unknown_revision`.

In the fixture, every predecessor is accepted except `b.install`, which is held on stale evidence, so `b.commission` is not eligible even though its cross-subsystem predecessor `a.commission` is accepted. Not checked: whether cited evidence exists, is accessible or is valid; whether the named role holds the authority it claims. Not implemented: sequence checks across stored event chains, budget, duplicate-spawn prevention and replay storage.

## Synthetic evaluation

Start with two subsystems, three phases each, one cross-subsystem dependency, one return for rework, and an independently supplied commercial observation. Use `Possible`, `Conditional`, `Ready` and `Executing` as transient simulator states and `Accepted` as an absorbing state for a fixed revision. A simulated acceptance is tagged synthetic and cannot produce an authority record. If the transient matrix $Q$ has spectral radius below one, solve $(I-Q)t=\mathbf{1}$ for expected steps to absorption and $(I-Q)b=c$ for expected cumulative cost with a declared per-step cost vector $c$. Steps are not calendar duration. If other terminal states are added, distinguish expected time to any terminal state from probability of acceptance. Coupled subsystems require a joint state or discrete-event replay; do not add per-phase means to predict project duration. Rates are illustrative until validated process mapping and event history exist.

## Acceptance checks before implementation is accepted

- Reproduce the pinned field, feature transforms, candidate readings, replay sequence and output digest. Keep whole trajectories separate in train and test; compare with a no-event control and a non-learning baseline before claiming added value.
- Reject invalid transition rows, unreachable absorption, dependency cycles, missing prerequisite revisions, and execution or acceptance transitions without the required scoped decision in the governance trace. Check the analytical toy result against a seeded Monte Carlo run. The simulation trace and governance trace are distinct.
- A frozen successor entry check can hold or return its predecessor; replay must not backdate or overwrite acceptance. Duplicate inputs do not double-spend simulated budget or spawn duplicate next phases.
- Confirm that geometric proximity, scores and labels cannot write confirmed edges, release work, or create ledger observations. Cash reconciliation may appear only from the separately supplied observation, not from a phase outcome.
- Before any use beyond synthetic fixtures, test two worlds that differ only in a restricted label or source record. To an unauthorized reviewer, derived counts, graph shape, scores, caches and exports must not reveal which world is present. Recheck source authorization before deriving or returning results, including after revocation; authorize positive controls separately. This document does not certify a permission boundary.

## Build order

Done: design page, described contracts, generated reference, forward-dependency and predecessor-acceptance checks and the two-subsystem fixture. Next: event-chain checks, then the array-free port and a deterministic infrastructure adapter. Evaluate the non-learning baseline before proposing an encoder or a viewer integration.
