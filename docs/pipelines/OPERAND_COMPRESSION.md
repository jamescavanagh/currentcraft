---
title: Six-domain evidence and versioned feature graph
version: 0.1.0
tags: [currentcraft, domain, features, evidence]
status: candidate implementation, unreleased
---

# Six-domain evidence and versioned feature graph

Supersedes the soil-profile experiment. The six contexts are Projects, Working
Docs, Commercial Orders, Subsystems, Site Acceptance Testing, and Feature
Compatibility. Existing aggregates keep their identities and local behavior;
this slice references them rather than creating replacement aggregates.

## Domain boundaries

| Context | Configuration link |
| --- | --- |
| Projects | Selected baseline |
| Working Docs | Evidence/revision lineage |
| Commercial Orders | Requested configuration, not fulfillment |
| Subsystems | Architecture mapping, not inferred equivalence |
| Site Acceptance Testing | Exact test basis, not acceptance authority |
| Feature Compatibility | Versioned definitions and constraints |

These are candidate domain descriptions, not certification or operational authority.
No shared physics is assumed.

## Private reference boundary

Standards names/editions, source links, clauses, domain crosswalks and enterprise
interpretations belong in the private server-side `REF` layer, not public design
pages, fixtures or generated examples. Proprietary mappings, business rules and
adapter implementations remain private too.

Authorized server-side adapters are intended to hydrate version-pinned references
into the private graph. Public code exposes only generic contracts, opaque
references and synthetic fixtures, and must work without private packages.

This page records the boundary; it does not implement REF storage, access control
or graph hydration, and does not claim that private sources have been moved.

## Contract rules

1. Operands are opaque UUID references to things with explicit record versions.
   Context and thing kind must match one of the six declared pairs. People,
   resources and parties are not operands. Existing entity IDs are never regenerated.
2. Configuration links have a context-specific predicate and opaque evidence IDs.
   No link means no asserted configuration fact. Model-valid, ordered, observed
   installed and test-passed are independent facts, not automatic transitions.
3. Features have stable UUID identities, separately numbered definitions, content
   digests, active/retired status, mandatory flags and evidence. Same identity and
   definition version cannot change contents. Removed does not imply retired.
4. Graph revisions are immutable, closed snapshots. Features, constraints and
   observations have unique identities; all references resolve within the snapshot.
   Constraints have distinct, active endpoints. Sets are canonicalized before hashing.
5. Valid and recorded times are timezone-aware and normalized to UTC. This slice
   requires recorded time at or after effective time; prospective scheduling is
   deferred. Observations cannot postdate the graph's effective or recorded time.
   There are no implicit wall-clock defaults.
6. Product observations pin exact product revisions. Present and explicitly absent
   features are disjoint and sourced. Unlisted features mean unknown. Complete
   selection evidence is explicitly flagged; it proves neither installation nor sale.
7. Encoding `mandatory-pairwise/v1` supports mandatory features, requires and
   excludes only. It is not a complete feature-model language, physical/interface
   compatibility checker, feature-group solver, numerical constraint solver or SAT
   implementation. Every result names the encoding and exact graph digest/revision.
8. Unknown/retired selections, missing mandatory features and violated constraints
   fail validation. Violation codes are deterministic. An allowed but unobserved
   configuration is possible, never an observed product. Exact complete observations
   are reported independently, even if the selected model rejects them.
9. The memory repository appends sequential revisions using compare-and-swap.
   Identical retries are no-ops; rewrites, backward recorded times, definition changes
   at the same version and version regressions fail. It is a single-process synthetic
   adapter, not thread-safe, durable or a database transaction.
10. As-of reads require effective time AND knowledge cutoff. Select the greatest
    eligible (valid_from, revision), with recorded_at <= known_at. Return none when
    no evidence exists; do not interpolate. Backdated corrections remain traceable.
    Diffs distinguish introduced, carried, changed, retired and no-longer-listed IDs.
11. Optional numerical compression still consumes explicit TensorRefs through the
    existing checked gauge path. It cannot create domain meaning or authority.
    The unmerged profile experiment's contract advances to v2, rejecting v1 soil
    payloads rather than silently migrating them. Simulation v2 is unchanged.
12. Only opaque references belong here. Actual source locators, enterprise terms,
    product identifiers and mappings remain private server-side. Recorded evidence
    is not verification of its truth or authorization to release work.

## Acceptance and limits

Synthetic tests cover the six contexts; old-context/soil rejection; canonical
hashing; stable identity and version immutability; introduce/carry/retire across
three revisions; as-of/knowledge-cutoff reads; typed relations/provenance; selected
model validation; unknown versus absent; allowed-but-unobserved and invalid-but-
observed selections; frozen contracts; layering; and generated-reference drift.

Implemented: reference/link contracts, graph snapshots, restricted validation,
append/as-of/diff service and synthetic memory adapter. Deferred: private ingestion,
SQL/HTTP integration, authentication, operational project/order/SAT workflows,
adoption-lag estimation, feature-group/SAT encodings, labeling, three-body mappings,
L-system productions, vocabulary promotion, simulation V3, merge and deployment.
This is unreleased 0.11 groundwork, not completion of 0.11 or upstream acceptance.
Package version stays 0.9.9; contract versions change independently.
