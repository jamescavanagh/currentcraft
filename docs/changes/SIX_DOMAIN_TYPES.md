---
title: Unreleased concrete six-domain types
version: 0.1.0
tags: [currentcraft, changelog]
status: candidate implementation, acceptance pending
---

# Unreleased: concrete six-domain types

Implemented six immutable proposal types: ProjectType, WorkingDocumentType,
CommercialOrderType, SubsystemType, SiteAcceptanceTestType and FeatureConfigurationType.
The first four reuse canonical entity classes and identity/version semantics;
canonical constructors, wire shapes and fail-closed lifecycle behavior are unchanged.
The new types have a separate currentcraft-six-types/v1 wire family. No automatic
legacy upgrade, reidentification, migration or definition promotion is performed.
SAT uses the existing test_record discriminator for profile compatibility.

Added exact configuration/model/selection bindings, sourced authorization references,
versioned order lines with exact quantities/units, subsystem interfaces/realizations,
source-reported test criteria and independently sourced acceptance references.
The application packet validator rejects known wrong project/configuration/document/
component versions and identity collisions. Unknown/inferred optional bindings remain
explicit gaps. It reuses the existing restricted feature-model validator without
turning model validity or test pass into ordering, installation or release authority.

Validation on the reconstructed slice and real retrieved dependencies: 84 tests
passed, zero failures/skips, including 47 new tests and 37 retained graph/profile tests.
Both generated-reference checks, Python compilation, shell syntax, limited release
scan and toolkit 0.1.1 staged-slice checks passed (zero layering/path findings,
five analytic controls). No dependency stubs were used.

Not run locally: full-repository CI/governance acceptance, PostgreSQL, NATS, Docker,
HTTP/ingest integration, private term/privacy certification and mathematical/process
SME acceptance. The sandbox has no internet access and no complete checkout; hosted
CI is separate evidence. Analytic controls are not domain/process validation.

Not implemented or claimed: source ingestion, durable storage, public DTOs/endpoints,
authority resolution, operational lifecycle transitions, automatic SAT threshold
interpretation, commercial price/tax/invoice reconciliation, physical compatibility,
new L-system productions, simulation V3, package version bump, merge or deployment.
The package stays 0.9.9; the six types remain v1-proposal.

Design: [Six concrete domain types](../domain/SIX_DOMAIN_TYPES.md).
Generated reference: [Six-type contracts](../contracts/SIX_DOMAIN_TYPES.md).
