---
title: Six concrete domain types
version: 0.1.0
tags: [currentcraft, domain, evidence]
status: candidate implementation, unreleased
---

# Six concrete domain types

Extends the merged six-domain foundation with domain-specific, immutable values.
`ProjectType`, `WorkingDocumentType`, `CommercialOrderType` and `SubsystemType`
subclass the existing canonical entities. They retain entity identity, record
version, evidence and the original validators; no canonical class is replaced.
`SiteAcceptanceTestType` and `FeatureConfigurationType` use the same versioned
entity base. All six have their own `currentcraft-six-types/v1` wire family and
remain `v1-proposal`. They are not automatically promoted to accepted definitions.
A new type is constructed explicitly; reading a canonical entity does not silently
upgrade, reidentify or migrate it. Original constructors and payloads are unchanged.

## Six meanings

1. Project: evidenced scope/phase, exact work packages/dependencies and a selected
   configuration baseline. ISO 21502/21511 are the design frame, not an imposed
   phase list or an allocation policy.
2. Working document: an exact captured source revision, derivation, supersession,
   latest received revision and separately evidenced authorization record.
   ISO 15489/23081 and W3C PROV inform lineage. Received is not authorized.
   Drawing stays separate; the original document transition still fails closed.
3. Commercial order: exact line identities/versions, explicit unknown or exact
   quantities/units, requested configuration, commitment and fulfillment references.
   REA/ISO 15944-4 and UBL inform the boundary. A line, PO reference, price or
   fulfillment reference is not authority or proof that a commitment was approved.
4. Subsystem: evidenced boundary, versioned components, interfaces, dependencies
   and sourced feature realization. ISO 42010 informs architecture description,
   not a claim that graph compatibility proves physical interoperability.
5. Site acceptance test: exact project/configuration, document-revision basis,
   conditions, source-reported criteria/results, observed configuration and time.
   IEC 62381 is a scoped process vocabulary, not universal commissioning policy.
   A separately sourced acceptance-decision reference is never created by passing.
6. Feature configuration: explicit configuration identity/version and selected
   features pinned to an exact model graph identity/revision/digest. ISO 26580
   informs the feature-model frame. Uses the existing mandatory/pairwise validator;
   source observation, installation, ordering and release remain separate.

## Rules

- Use existing `VersionRef`, `Fact`, `Quantity` and `UnitRef`. Unknowns retain reasons;
  a blank cannot become zero. Known source assertions require evidence. New evidence
  tuples and reference collections reject duplicates, including duplicate target
  identities at conflicting versions. Self-dependencies and self-supersession fail.
- Every configuration binding pins configuration identity/version, graph identity,
  graph revision/digest and a canonical selected-feature digest. Identical feature
  sets have the same selection digest regardless of order. Duplicate selections fail.
- Project-linked canonical subtypes retain `project_id` and add its exact record
  revision. SAT and configuration carry exact project VersionRefs.
- A document authorization assertion requires exact revision, decision and evidence.
  It records a claim only; no resolver checks the actor's authority. Latest received
  may differ from authorized; a newer receipt must not overwrite authorization.
  Supersession must reference a different revision from the captured revision.
- Order lines are uniquely identified, carry explicit versions, and use exact
  nonnegative Quantity values or explicit unknown. Zero remains zero. A known
  line-level requested configuration cannot conflict with a known order-level one.
- Interface local endpoints and feature realizations must reference exact declared
  component versions. Each interface and realization identity is unique. Interface
  peers may be outside the local boundary and are not silently resolved.
- A criterion's `pass`/`fail` requires known expected and source-observed values plus
  evidence. This slice does not evaluate textual/numeric thresholds automatically.
  A test-level pass requires nonempty all-pass criteria, source-observed overall
  result/time and an observed configuration equal to its exact test configuration.
  A test-level fail needs at least one failed criterion; unexecuted or inconclusive
  criteria cannot silently become a pass. Acceptance reference remains independent.
- All six freeze their values and reject extra keys. No automatic lifecycle
  transitions, authority checks, allocations, source reads, I/O or persistence.

## Cross-record validation

A packet carries exactly one of each type and its model snapshot. Validation:

1. Checks exact project identity/revision across all five linked types.
2. Checks known project/document/order/subsystem bindings, every known order-line
   binding and the test's required binding against the exact configuration object.
   Unknown optional bindings produce explicit gaps; they are not passes.
3. Requires the test basis to include the supplied document's exact captured revision.
   No title/name matching, latest-revision substitution or authorization inference.
4. Requires every realization feature to belong to the selected configuration.
5. Calls the existing feature validator against the pinned graph. Returns its outcome
   independently of packet consistency: an invalid-but-observed configuration remains
   recorded, and model-valid is not release. Missing optional bindings yield incomplete,
   while known mismatches fail closed with fixed codes and no source labels.

The packet validates consistency of supplied records, not completeness of an entire
project or the authenticity of evidence. It checks supplied source snapshots, not
whether they are the current head. No retrospective overwrite or publication.

## Acceptance and exclusions

Tests cover all six types, canonical subtype/identity stability, legacy constructors,
unknowns, quantities, exact bindings, receipt versus authorization, criterion/test
consistency, wrong configuration/project/document/component versions, duplicate/self
references, feature realization, graph pinning, generated docs and layer boundaries.
Public fixtures are synthetic; original locators, customer names, part numbers and
private mappings never enter examples or outputs. Domain objects are not public DTOs;
no HTTP serializer or public endpoint is added.

Not implemented: ingestion, durable storage, HTTP APIs, operational lifecycle policy,
actual authority verification, arithmetic/threshold-based SAT, tax/pricing/invoice
reconciliation, physical compatibility, feature-adoption lag, new grammar productions,
V3 simulation, version bump, merge or deployment. The six types remain proposals.
