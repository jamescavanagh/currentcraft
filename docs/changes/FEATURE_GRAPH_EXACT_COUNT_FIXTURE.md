---
title: Exact-count feature graph regression fixture
version: 0.1.0
tags: [currentcraft, feature-graph, regression, synthetic]
status: test-only design; implementation and CI evidence tracked in the pull request
---

# Exact-count feature graph regression fixture

## Purpose and rules

Protect the existing standalone `mandatory-pairwise/v1` validation semantics with an independently enumerated synthetic oracle. This is a test-only count, not a new production counting API, SAT solver or MDD implementation.

Four Boolean features have 16 assignments. Feature 1 is mandatory; feature 2 requires feature 3; feature 3 excludes feature 4. The exact allowed set is `{1}`, `{1, 4}`, `{1, 3}`, `{1, 2, 3}`: four configurations. Removing the pairwise constraints leaves eight configurations with feature 1 mandatory; making it optional leaves all 16. These controls ensure both the constraints and mandatory requirement affect the count.

A complete observation of `{1, 3}` is model-allowed. A complete observation of `{1, 2}` violates the requirement but remains an observation. Neither observation changes the exact count or grants authority. Every result, including violations and observed configurations, remains `candidate_only=True`; explicitly setting it to false must fail contract validation.

## Acceptance tests

- Enumerate all 16 assignments through the existing graph service and compare the exact allowed set, not just its size, to the hand-derived oracle.
- Check exact counts of 16 and 8 in unconstrained and mandatory-only controls.
- Check observation receipts, model outcomes and evidence statuses independently for every assignment.
- Check exact graph identity, revision, digest and request digest on every receipt.
- Check candidate-only enforcement for possible, observed/allowed, observed/violating and unobserved/violating results.
- Verify enumeration leaves the graph and repository history unchanged.

## Changelog and limits

Added: a standalone unittest regression module, `tests/test_feature_graph_exact_count.py`, using synthetic opaque identities and the existing memory repository composition root.

Unchanged: production code, standalone validation contracts and semantics, persisted identity algorithms, candidate-only boundaries, hydration and operational authority.

Not claimed: production exact counting, SAT/MDD performance or equivalence, real-world model validity, readiness, approval, release or process benefit. No runtime dependency or release version change is required for this test-only slice. Passing this fixture does not certify larger counts from the synthetic benchmark.

## Run

`PYTHONPATH=src python -m unittest discover -s tests -p 'test_feature_graph*.py' -v`

Full acceptance remains `bash scripts/ci_public.sh` and `dmgov accept .`; report actual results separately, never infer them from this test's presence.
