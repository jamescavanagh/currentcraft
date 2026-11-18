# V1 enterprise slice

P0–P3 extensions, synthetic acceptance examples and unresolved decisions are recorded in [P0_P3_CAPTURE.md](P0_P3_CAPTURE.md); the 84-row phase inventory is [PHASE_TRACEABILITY.json](PHASE_TRACEABILITY.json). These capture additions do not change the unapproved operational policies below.

Status: implementation proposal for review, not an accepted operating policy.
Patch base: `2a6dbfd64745f78a727a3af76c1157de2d869857` (0.9.9).

## Sources and precedence

S1: supplied enterprise implementation work order (Pasted text(4).txt).
S2: supplied DataMesh Project-Agency Toolkit, November 11, 2026.
S3: supplied historical class diagram, wireframe class diagram v2(1).mermaid.
S4: repository PROCESS_FIRST.md and existing process/persistence contracts.
S5: James's instruction in this conversation to retain Pydantic in the domain.
S5 supersedes S1's standard-library-only restriction. No performance benchmark
is claimed. Domain classes use Pydantic v2; HTTP, drivers, file reads, numerical
arrays, persistence and dispatch remain outside the domain.

The five governing task references in S1 could not be read. Their semantics are
an acceptance blocker. Private source URLs and contents are not copied into this
public patch. S3 is historical evidence, never approval of disputed inheritance.

## Common contracts

All implemented entities retain their original import paths. Their schemas are
explicitly `v1-proposal`; construction requires an opaque UUID. An ERP number,
task key or model number is an ExternalReference(namespace, key), never an ID.
Typed UUID aliases describe relationship endpoints; application validation also
checks the referenced record's actual class and project ownership.

Entity record_version is a positive snapshot version; schema_version describes
the payload shape. The existing VersionedRecord envelope owns persisted CAS
history. Entities never increment repository versions or save themselves. Capture saves each entity under the existing enterprise_entity aggregate key and its explicit record_version, atomically with the snapshot and outbox event. Changed entity content requires its next revision; repeated content reuses its current revision. Entity kind changes require an explicit migration; none is supplied.

Fact[T] holds value, missing_reason and evidence_ids. A missing value is null
with a nonblank reason. A known value has no missing reason and must cite source
evidence. Valid zero is retained. Optional structural links also use Fact[ID].
Empty tuples mean no assertions recorded, not proof that none exist.

Field authority: opaque identity and envelope metadata are assigned by the
application; source facts belong to the cited source, and inferred facts must
cite evidence marked inferred. Source assertions do not establish decision
rights. The mapper is explicit and rejects undeclared record types and fields.
No runtime Python imports or executable classes come from reference data.

QualityEvidence is the canonical source assertion: source namespace/version,
locator, valid-time window, recorded time, observed/inferred/unknown status,
optional content hash and supporting evidence IDs. Ingestion Provenance remains
its existing intake/adapter lineage contract; it is explicitly linked by locator
when mapped and is not replaced by a competing domain evidence envelope.
Time is timezone-aware; windows have exclusive end and start < end.

Quantity is finite nonnegative Decimal plus a versioned unit reference. Float
input and bool are rejected; there is no implicit conversion. Addition requires
the same unit reference, including dictionary/version. Zero is valid. Money is
source text and available currency/context facts only; there is no arithmetic.

## Implemented entity definitions

All rows inherit the identity, version, evidence, missing-value, authority and
relationship rules above. Concrete fields and requiredness are generated into
the existing contract documentation and JSON Schema pipeline. Labels and
minimal field selections are implementation proposals, not newly confirmed
KCM vocabulary. Unless noted, lifecycle is immutable capture only: no release,
side effects or transitions are inferred from record construction.

| Type / kind | Meaning, fields and relationships | Units / lifecycle / invariants | Sources / gaps |
| --- | --- | --- | --- |
| ExternalReference / value | namespace and source key | no internal identity or authority | S1; namespace ownership is caller configuration |
| Fact / value | typed value, missing reason, evidence IDs | null requires reason; known requires evidence | S1,S2 |
| TimeWindow / value | start/end timestamps | aware, exclusive end after start | S1; half-open convention proposed |
| UnitRef, Quantity / values | dictionary, version, stable unit code; exact amount | no implicit conversion, no negative physical quantity | S1; no KCM dictionary invented |
| SourceMoney / value | source text; currency/context facts | preserve text, no parsing/calculation | S1 |
| VersionedEntity / entity base | UUID, version, schema, external refs, evidence IDs | immutable proposal; accepted-definition guard still blocks | S1,S4; review pending |
| QualityEvidence / evidence entity | source/version/locator/status, valid/recorded time, source hash | no assertion of source truth or human approval | S1,S2; identity/time supplied |
| Party / entity | shared party identity and evidenced name | no implicit role or decision rights | S1; added because Organization is only a placeholder |
| Resource / entity base | party ID and evidenced name | execution identity distinct from party; no implicit permission | S1; exact permissions unresolved |
| Employee / resource | employment kind fact | full_time, part_time, temporary are S1 categories; unknown allowed | S1; sibling of Contributor |
| Contributor / resource | third-party labor and provider-party fact | sibling of Employee | S1 |
| Agent / resource | AI model reference fact | never human authority | S1; permission policy unresolved |
| Client, Vendor / classifications | party ID | classification does not grant authority | S1 |
| Four vendor classes / classifications | existing four canonical meanings retained | never enforce overlap or exclusivity | S1; overlap remains open |
| Stakeholder / relationship | party, project, contextual role | no approval rights | S1 |
| Consultant / engagement | party, project, contextual role | approvals need explicit execution/authority/evidence | S1; no blanket approval |
| ManufacturerRep / relationship | representative party, manufacturer party, project | no identity inheritance or approval rights | S1 |
| Project / entity | evidenced name and external refs | no invented commercial lifecycle | S1 |
| Phase / entity | project and evidenced name | lifecycle phase only; stage mapping is explicit application data | S1,S4 |
| WBS / entity | project and evidenced code | no inferred nesting/task hierarchy | S1 |
| Subsystem / entity | project and evidenced name | no extra hierarchy imposed | S1 |
| Task / entity | project, name, optional subsystem/phase/WBS facts | not a ClickUp task or process execution | S1 |
| ProductDefinition / entity | catalog name, manufacturer-party, model facts; bulk flag | catalog identity distinct from physical identity | S1 |
| AssetInstance / entity | product/project and serial/MAC/IP/firmware/installation facts | reject creation for bulk definitions at boundary; no quantity side effects | S1; address facts retained as source text |
| Document / entity | project, source version and storage locator facts | transitions blocked until approved lifecycle policy exists | S1; drawing decision deferred |
| BOM, BOMLine / entities | project, stage fact; BOM/product/quantity links | separate IDs at each ROM/material-list/PO stage, no automatic conversion | S1; names proposed, transitions unresolved |
| Shipment, ShipmentLine / entities | project; line links to product quantity or existing asset | exactly one line variant; no custody/holding mutation | S1; holding workflow unresolved |
| CalendarBooking / reservation record | resource, project, task, window | time bounded; not execution authorization or a live allocation | S1 |
| RFI / entity | project, question, response, contextual impact IDs | no scope, drawing or cost approval implied | S1 |
| Order / commercial entity | project, counterparty fact, document references | independent from Document; no procurement execution inferred | S1 |
| ProcessType, ProcessExecution, ObjectIncidence, CapabilityBinding, AuthorityRef / existing application contracts | reuse existing canonical contracts unchanged | people only in resource bindings, not incidence; positive operational authorization is blocked while policy is undefined | S1,S2,S4; full authority model pending |
| ReferenceDictionary / application value | schema/dictionary/version, validity, synthetic marker, canonical QualityEvidence, units/stages/process catalog and payload hash | immutable selection; loader checks whole-file hash; duplicate IDs/types/fields rejected | S1,S2; caller supplies trusted root and hash |
| StageMapping / application value | lifecycle phase ID and selected execution stage code | explicit mapping required, never derived from simulator phase | S1,S4 |
| CapabilityAssertion / application value | selected process code and existing CapabilityBinding | source evidence and actual resource must resolve; does not authorize work | S1,S4 |
| ExecutionLink / application value | project, task and phase IDs plus existing ProcessExecution | cross-project inconsistencies rejected; no new process identity model | S1,S4 |
| EnterpriseSnapshot / application aggregate | opaque snapshot ID, capture time, purpose, selected reference/hash, records and explicit mappings/assertions/executions | immutable versioned capture, statically allowlisted hydration; no implicit startup hydration | S1,S2; synthetic capture is not process validation |

## Readiness and authority

No enterprise policy has been supplied for Possible -> Conditional -> Ready ->
Executable/Returned. The application validates references, capability evidence,
stage mapping and human-scoped decision evidence before it even reaches the
policy boundary. Every operational transition then fails with an explicit
policy-not-defined error. Neither an AuthorityRef role label, a synthetic grant,
a completed task nor a booking unlocks this boundary. Positive releases are not
implemented or claimed. Existing analytical ProcessExecution validation is
retained for compatibility and is not an enterprise permission service.

Document lifecycle transitions likewise fail closed; no guessed state machine
is installed. The snapshot fixture contains captured records and read-only
process observations, not executable commitments.

## Decision-gap ledger

| Gap | Treatment / required decision |
| --- | --- |
| Governing semantic tasks unavailable | acceptance blocked pending source review |
| Human authority and permissions | deny all operational transitions; define grant/executor/context/scope/evidence/revocation policy |
| Readiness and document lifecycle | deny transitions until evidence criteria and policies are approved |
| Drawing as document | keep existing Drawing placeholder, no inheritance chosen |
| Vendor overlap | retain named classifications without overlap/exclusivity constraint |
| WBS/task/phase nesting | explicit optional links only; no inferred hierarchy |
| Shipment custody/holding | capture references only; no physical movement side effects |
| Cross-plane order vocabulary | Order is independent; no automatic document/procurement conversion |
| Business dictionaries / field owners | synthetic references only; no production dictionary or authority owner inferred |
| Other legacy classes | unchanged, remain unreviewed placeholders |

## Migration

Existing module/class imports remain. Implemented classes now require real UUID
identity and their documented fields: zero-argument placeholder construction and
the two-field-only schema are intentionally discontinued for those classes.
Records with no identity are not automatically migrated. Unchanged placeholders
retain the old constructor/schema/fail-closed behavior. The scaffold manifest
is still the historical inventory, not an approval list; its generator now
distinguishes implemented proposals from remaining scaffolds.

## Reproducible fixture

After installation, run `python examples/domain_bootstrap.py` from the repository.
The composition root loads an explicitly synthetic, hash-pinned reference file,
builds evidenced records in dependency order, maps an allowlisted snapshot,
checks references, saves it and one domain.stored event atomically through the
existing UoW/outbox, and reloads/revalidates it. Stable fixture UUIDs and times
make output reproducible. No external services or production allocations occur.
