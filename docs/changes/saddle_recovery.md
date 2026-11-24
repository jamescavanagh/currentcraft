---
title: Seed-robust critical-point recovery
status: implementation-candidate
version: 0.1.0
tags: [simulation, numerical-recovery, synthetic]
---

# Seed-robust critical-point recovery

## Invariants

Union grid seeds with warm-start coordinates without changing the field,
Newton step, residual threshold (1e-9), strict extent acceptance, 1e-3 root
deduplication or classification. Numpy stays in infrastructure. Request
schemas, canonical node ordering, digests and persisted identities are unchanged.

## Continuation

The already increasing inflow sweep carries all recovered roots into the next
slice. Warm coordinates are never accepted without a fresh solve and residual
check. An internal explicit-seed seam supports reproducible testing, not a new
request field. Initial discovery remains grid-dependent: a root never found
cannot be carried forward. A recovery miss is unresolved, not disappearance.

## Collision refinement

Retain roots at both bracket ends. Each midpoint solve uses the union of both
endpoint root sets plus the configured grid; updating an endpoint also updates
its roots. Inconsistent endpoint counts and midpoint counts outside the closed
range of the two endpoint counts raise source-free numerical errors. Events remain numerical
estimates, not completeness or collision certificates. Equal-count intervals
can hide transitions; multi-count brackets can contain several events and are
not certified single collisions. Labels attach to independently matched tracks, not
result-array positions; no persistent track identifiers are added here.

## Tests and private acceptance

Public tests use synthetic fields and vortex configurations only. Cover cold
behavior, root revalidation, small-basin recovery, real root loss, bracket
propagation and fail-closed refinement. Cross node shuffles with grid, jittered
and uniform seed ensembles, matching saddle coordinates within 1e-3 rather
than index. Full points and tensors must agree across node permutations for
each seed set. Cross-seed core completeness is not claimed: the synthetic
matrix exposes a coarse-grid core miss even while saddle/event parity passes.
The genuine synthetic vortex small-basin regression also verifies that cold
restarts miss a saddle recovered by continuation and by an 80-per-side grid.
Its negative control runs against the pinned cold implementation, not an
independently obtained historical release binary.

DATAMESH_PRIVATE_SADDLE_CASE points to an untracked JSON case outside the
checkout. It provides request, source SHA-256, baseline revision, provenance,
reference digest, per-slice saddles and unrounded events. Source bytes and
reference digest are verified before execution; this is integrity, not proof
of reference authority. No private values enter the public tree or PR body.

The runner executes the prescribed 35 seedings (five grid densities, 24
half-cell jittered grids, six uniform sets), each with original and reversed
node order. Require complete reference-saddle recovery, no extras/kind flips,
matching event directions and event locations within 1e-4. Expected slice,
event and saddle-label totals come from the private approved reference, not
public hard-coded source inventories. The acceptance operator checks those
counts against the governing private case before treating a run as evidence.
Missing configuration is skipped explicitly, or fails when
DATAMESH_REQUIRE_PRIVATE_SADDLE=1. Invalid or inaccessible cases fail without
payloads, identifiers, paths or upstream exceptions in the output.

The coordinator supplies a reconciled, approved unrounded baseline. Never pick
between conflicting rounded references, derive reference data from the
candidate, or relax tolerances. Public tests, CI, governing checks and private
acceptance are separate evidence. Skipped private acceptance is not a pass.

## Non-claims

No field modification, BLF, certified disappearance, process validity, release,
merge or deployment. The existing unreleased package version is unchanged;
CHANGELOG records implemented behavior and remaining acceptance limits.

## Private runner envelope (not a runtime ingestion contract)

Run `python -m unittest tests.test_private_saddle_gate` with the environment
variables above. The JSON case contains:

- `version`: `private-saddle-acceptance/v1`.
- `source_file`: external file containing a serialized NodeInteractionRequest;
  `source_sha256`: SHA-256 of those exact bytes.
- `baseline_revision`: full baseline commit SHA.
- `provenance`: nonempty `source_version`, `method`, `run_reference`,
  `approval_reference`, and a 64-character `mapping_sha256`.
- `reference`: `expected_slices`, `expected_events`,
  `expected_saddle_labels`, `slices` and `events`. Each slice has `inflow` and
  `points` containing saddle `x`, `y`, `kind`. Each event has `inflow`,
  `saddles_before`, `saddles_after`.
- `reference_sha256`: SHA-256 of UTF-8 JSON for `reference`, with sorted keys,
  compact separators and nonfinite numbers prohibited.

Both the case and source file must resolve outside the checkout and be regular
files of at most 10 MB. This is a trusted private test input, not a hostile-file
sandbox. Approval references are recorded provenance, not programmatic proof
of authority. The runner never creates or updates its own reference.
