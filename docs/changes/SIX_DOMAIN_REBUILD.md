---
title: Unreleased six-domain rebuild
version: 0.1.0
tags: [currentcraft, changelog]
status: unreleased, acceptance pending
---

# Unreleased: six-domain evidence and versioned feature graph

## Implemented

- Replaced the branch's eleven-context soil-profile model with six typed context,
  thing-kind and evidence-backed configuration links. Existing aggregates are
  referenced with unchanged opaque IDs and exact record versions, not redefined.
- Added stable feature IDs, separately versioned definitions, typed pairwise
  constraints, dated product observations, provenance and canonical snapshot digests.
- Added selected-model validation, two-clock as-of reads, identity-level snapshot
  comparison and an append-only compare-and-swap synthetic memory repository.
- Kept model validity separate from source observations and all order, installation,
  test and release authority. Unlisted features remain unknown; omission is not retirement.
- Repaired malformed TOML and registered the new packages/release paths without
  removing existing API or release gates. Added generated-reference drift checks.
- Kept optional checked gauge compression downstream. Its profile request family
  is v2 because the unmerged v1 soil payload is incompatible; simulation v2 and
  existing persisted identities are unchanged. No silent legacy migration.

## Verification

37 focused synthetic tests passed, zero skips, using the real Pydantic models,
real application code and synthetic memory adapter, without dependency stubs.
Generated reference --check, TOML parsing, Python compilation, shell syntax,
limited release scan and toolkit 0.1.1 checks passed on the staged slice only.
The toolkit archive checksum matched the registered 0.1.1 package. Five analytic
controls passed; these control results are not evidence of product/process validity.

## Not run or claimed

Full-repository CI and full-checkout governance acceptance were not run locally:
only the changed slice and the retrieved real common base were available, and the
sandbox has no internet access. The optional gauge bridge was compile/static
checked, not numerically exercised in this local run. PostgreSQL, NATS, Docker,
HTTP/ingest integration and private enterprise-term certification were not run.
A hosted CI result must be checked separately against the final commit.

No production repository, live source ingestion, solver beyond mandatory/pairwise
constraints, physical interoperability, feature-adoption lag estimate, three-body
mapping, new L-system productions, vocabulary approval, simulation V3, 0.11 release
completion, package version bump, merge or deployment is claimed.

The six context links are reviewable contracts, not implementations of all five
operational domain workflows. The graph is the narrow executable slice.
