---
title: Six concrete domain types
version: 0.2.0
tags: [currentcraft, domain, evidence]
status: candidate implementation, unreleased
---

# Six concrete domain types

Canonical entities stay authoritative. The six types are **extensions composed over
canonical entities by reference**, not subclasses of them. Each extension has its own
`extension_id` and `extension_version`, independent of any canonical identity or record
version, and holds exact kind-tagged `CanonicalRef` values (kind, identity, version):
`ProjectExtension` references a canonical `Project`, `WorkingDocumentExtension` a
`Document` and its `Revision`s, `CommercialOrderExtension` an `Order`, and
`SubsystemExtension` a `Subsystem` and its components. `SiteAcceptanceTestExtension`
and `FeatureConfigurationExtension` are extension-native records that reference the
canonical project. Canonical classes, constructors and wire payloads are untouched and
never re-serialized inside an extension. All six use the `currentcraft-six-extensions/v1`
wire family, remain `v1-proposal` and are not promoted to accepted definitions. The
earlier `currentcraft-six-types/v1` subclass family is not upgraded or migrated.

## Six meanings

1. Project: evidenced scope/phase, exact work packages/dependencies and a selected
   configuration baseline. This capture does not impose a phase list or allocation
   policy.
2. Working document: an exact captured source revision, derivation, supersession,
   latest received revision and separately evidenced authorization record.
   Received is not authorized. Drawing stays separate; the original document
   transition still fails closed.
3. Commercial order: exact line identities/versions, explicit unknown or exact
   quantities/units, requested configuration, commitment and fulfillment references.
   A line, PO reference, price or fulfillment reference is not authority or proof
   that a commitment was approved.
4. Subsystem: evidenced boundary, versioned components, interfaces, dependencies
   and sourced feature realization. Graph compatibility does not prove physical
   interoperability.
5. Site acceptance test: exact project/configuration, document-revision basis,
   conditions, source-reported criteria/results, observed configuration and time.
   A separately sourced acceptance-decision reference is never created by passing.
6. Feature configuration: explicit configuration identity/version and selected
   features pinned to an exact model graph identity/revision/digest. Uses the
   existing mandatory/pairwise validator; source observation, installation,
   ordering and release remain separate.

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

## Rules

- Use existing `VersionRef`, `Fact`, `Quantity` and `UnitRef`. Unknowns retain reasons;
  a blank cannot become zero. Known source assertions require evidence. New evidence
  tuples and reference collections reject duplicates, including duplicate target
  identities at conflicting versions. Self-dependencies and self-supersession fail.
- Every configuration binding pins configuration identity/version, graph identity,
  graph revision/digest and a canonical selected-feature digest. Identical feature
  sets have the same selection digest regardless of order. Duplicate selections fail.
- Every extension carries one exact canonical project reference. Every canonical
  reference is kind-tagged; fields accept only their allowed kinds (for example a
  captured revision must be a `revision`, a component an `asset_instance`,
  `product_definition` or `subsystem`). An extension identity may not equal any canonical
  identity it references. Each extension enumerates its references with role, whether
  required, and the ownership it expects, for resolution.
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

## Canonical reference resolution

Local validation checks shape and allowed kinds only. Whether a reference is real is
decided through an explicit port, `CanonicalReferencePort.lookup(CanonicalRef)`, one
instance per authorized scope. The port returns found, not found, version absent or
access denied, plus the stored kind, identity, exact version, record digest and owner
facts read from an allowlist of canonical owner fields (`project_id`, `document_id`,
`system_id`, `phase_id`, `parent_wbs_id`, `product_definition_id`, `contract_id`,
`reference_set_id`). No latest-version substitution; no name or title matching.

For each reference `resolve_extensions` checks:

1. **Kind**: stored kind equals the declared kind, otherwise `kind_mismatch`.
2. **Version**: the exact identity and version exist, otherwise `version_absent`
   (identity exists at another version) or not found.
3. **Project ownership**: a record owned by a project belongs to the extension's project,
   otherwise `project_owner_mismatch`. Fields that legitimately cross projects
   (dependencies, derivation sources, interface peers, specifications, evidence) opt out.
4. **Document-revision and other ownership**: where the extension expects its subject as
   owner (captured, superseded, latest-received and authorized revisions belong to the
   extension's document), the owner must equal the subject, otherwise `owner_mismatch`.

Outcomes: `blocked` on any mismatch, missing required record or denied access;
`unverified` when a reference is an unresolved optional candidate, an owner is unknown
or the standard has no rule for the kind; `canonically_verified` only when every
reference is verified. The report carries codes and digests, never labels or source
text, and grants no authority.

## Ownership from the referenced standard

Which ownership relations exist, and which are required, is not hard-coded. It comes
from an ownership profile (`framework-ownership/0`) pinned to the domain's referenced
standard: the exact framework profile (`framework_id`, `framework_edition`,
`profile_version`, `source_digest`). Each rule names a subject kind, an owner kind, the
allowlisted owner field and whether it is required, and cites the framework concept it
is drawn from; the concept must map to the rule's subject or owner. Root kinds are owned
by nothing. A kind with no rule stays unverified.

Real ownership profiles live in private `REF` and are loaded by the infrastructure
loader: explicit absolute root, contained path, no symlinks, size limit, SHA-256 pin,
closed JSON and an as-of check inside the validity window. The public fixture
`tests/fixtures/framework_profiles/synthetic_ownership.json` is bound to the synthetic
`SYN-A` profile and represents no adopted standard. Identity-level ownership is what the
canonical records state: canonical owner fields hold identities, not versions.

## Acceptance and exclusions

Tests cover all six extensions, composition (no canonical subclassing), separate
extension identity/version, untouched canonical entities, kind-tagged references,
resolution through the port (wrong kind, absent version, project and document-revision
ownership, unknown owners, kinds without a rule, missing required versus optional,
denied access), ownership-profile binding and loading,
unknowns, quantities, exact bindings, receipt versus authorization, criterion/test
consistency, wrong configuration/project/document/component versions, duplicate/self
references, feature realization, graph pinning, generated docs and layer boundaries.
Public fixtures are synthetic; original locators, customer names, part numbers and
private mappings never enter examples or outputs. Domain objects are not public DTOs;
no HTTP serializer or public endpoint is added.

Not implemented: a durable canonical-store adapter (the port adapter here resolves an
explicit snapshot), owner-chain traversal beyond one hop, canonical quality-state mapping
for SAT results, line-scoped order configuration, ingestion, HTTP APIs, operational lifecycle policy,
actual authority verification, arithmetic/threshold-based SAT, tax/pricing/invoice
reconciliation, physical compatibility, feature-adoption lag, new grammar productions,
V3 simulation, version bump, merge or deployment. The six types remain proposals.
