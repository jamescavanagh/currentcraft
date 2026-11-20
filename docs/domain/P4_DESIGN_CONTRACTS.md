# P4 design contracts and migration checkpoint

Status: **reviewable architecture and migration baseline; no orchestration, operating grant or production publication**. PR #4 established the application DTO foundation and was merged. This follow-up is based on public `main` at `45e5400a7e3e016711b69f333bb1216da655fe8b`. James's superseding P4 requirements govern business meaning. This page owns the design and reuse decisions; executable DTOs remain in `app.application.p4.contracts` until a separately reviewed migration.

Companion specifications:
- [Source/destination boundary](../architecture/SOURCE_ADAPTER_BOUNDARY.md): public contracts, sanitization and private composition.
- [P4 integration plan](../architecture/P4_INTEGRATION.md): transaction sequence, checkpoints, delivery and recovery.
- [Persistence](../architecture/PERSISTENCE.md): existing repository/UoW guarantees and verification limits.

## Provenance and limits

- **James requirement:** Workflow I runs are workflow subjects; refresh creates a new run; five public states; automatic publication after integrity checks; Published only after destination acknowledgment; warnings for honestly represented gaps; collision and double counting block; previous successfully published version is the delta baseline; no private Acumatica or part references in the public repository.
- **Developer encoding:** UUID identities, per-aggregate monotone versions, pinned inputs, SHA-256 canonical request fingerprints, committed process/transition/decision links, explicit gate results and allowlisted ingress. These remain reviewable technical proposals, not production policy.
- **Synthetic only:** `workflow-i-synthetic-publication/v1`, `workflow-i-synthetic-calendar/v1`, synthetic source/destination and opaque IDs. No KCM accounting or operating authority follows.
- **Unresolved production configuration:** destination operation/location and completion semantics; source-safe labels; reporting cutoff; real adapter capabilities; accounting mappings; authorization/access control; accepted live measure definitions.
- The 17 P4 domain concepts remain deferred. A file named for a concept does not implement it: inspected `StateTransition` and `GateDecision` are still `ScaffoldRecord` subclasses with definitions pending review. No traceability completion or generator registration is claimed here.

## Canonical reuse map

| Concern | Existing owner | Decision / boundary |
| --- | --- | --- |
| Shared identity, facts and evidence | `app.domain.shared.identity`, `facts`, `quality_evidence`, `versioning` | Reuse opaque identity and immutable capture vocabulary. Preserve historical limitations and independent reference verification. A shared identity type is not automatically a drop-in replacement for `VersionRef`. |
| Process provenance | `app.application.process.contracts.ProcessExecution`, `ObjectIncidence`, `CapabilityBinding`, `AuthorityRef`; `lifecycle.derive_object_events` | One canonical execution per applied transition. Objects are things; resources execute. Derived object events are not a second authored history. `decision=release/hold/reject/return` is an effect, not a lifecycle state or sufficient authorization. |
| Workflow state / transition | `app.domain.workflow` scaffolds, current P4 `AppliedTransition` | Implement reviewed domain definitions later. Keep P4 index/reference semantics; do not create an independently writable transition log. |
| Human gate decisions | `app.domain.quality.gate_decision.GateDecision` scaffold; current `CommittedGateDecisionRef` | Future full decision owns actor, bounded authority, purpose, evaluation and exact target versions. The P4 ref is a read-only integrity view, not an approval. |
| Persistence | `VersionedRecord`, `AggregateRepository`, `CommandRecord`, `CommandLog`, `UnitOfWork` | Store reviewed P4 payloads using existing aggregate history and CAS. Add no parallel command/event database. Existing records do not implement P4 checkpoint or request-fingerprint semantics by themselves. |
| Command replay | `app.application.persistence.services.run_once` | Retain general behavior; do not use it unchanged for P4 admission: it returns prior outcomes without comparing request content. Validate P4 fingerprint before returning a prior run. |
| Outbox / broker | `app.application.messaging.EventEnvelope`; UoW outbox and `relay_outbox` | Commit with changes, relay after commit; at-least-once effects need deduplication. Broker acknowledgment is not destination receipt. |
| HTTP composition | `app.interfaces.http` app/container/wiring | Inject configured adapters through the composition root later. No synthetic fallback for unconfigured live integration. |
| Cross-phase concepts | `data_governance.data_product`, `data_lineage`, `commercial.cost_code` | Review minimum dependencies explicitly; do not mark all later-phase scaffolds complete. |
| Commercial identities | `commercial.commercial_order.Order`, `Contract`, `materials.bom_line` | Reuse Order; a source line is not implicitly a BOMLine. Contract means company/client; subcontracts belong to other stakeholders. No NLP extraction in this scope. |
| Schemas / docs | `gen_agency_contract_docs.py`, `gen_openapi.py`, `gen_domain_scaffold_docs.py`, scaffold tests | `CONTRACTS` below is an inventory, not generator registration. Register reviewed models/routes with existing generators later; never hand edit generated files. |
| Private integrations | Private Acumatica adapter, key/part crosswalks, ClickUp credentials and destination wiring | Stay outside public packaging. Public conformance uses synthetic records and destinations only. |

Dependency order: reviewed contracts/domain decisions -> reviewed source/destination ports -> persistence/checkpoints -> measures/graphs -> delivery acknowledgment -> HTTP. `docs/ROADMAP.md` is historically stale; it cannot override the superseding P4 brief.

## Complete existing application-contract inventory

All definitions below are retained at their existing import path in this checkpoint. No fields, defaults, validators, serialization, fingerprints or function signatures change. `CONTRACTS` lists the 15 concrete payload models; support types, aliases and module helpers have separate inventories. These are references to definitions, not copies or new schemas.

| Existing symbol | Current responsibility | Disposition and possible later home |
| --- | --- | --- |
| `Frozen` | Frozen, extra-forbid validation base | Retain. Compare shared `_Frozen` configuration before any compatible alias; never substitute silently. |
| `VersionRef` | Immutable UUID/version reference | Retain application reference. Evaluate shared-version reuse only after strictness, hashability and serialized-shape comparison. |
| `WorkflowIIdentity` | Distinct project/product/run/evaluation/graph/attempt identities | Retain application composition DTO; do not turn it into a second workflow aggregate. |
| `ReportCalendar` | Versioned local cutoff and date-only fallback | Retain application configuration. Production DST resolution remains a prerequisite. |
| `GenerationRequest` | Admission parameters, fingerprint and retry comparison | Retain application command. Resolve persistence key-length mismatch without changing the accepted request contract. |
| `ExtractionManifest` | Extraction identity, consistency capability, completeness and digest | Retain public application envelope; private source snapshot handles must not leak through its string fields. |
| `Association` | Candidate/confirmed relation evidence | Retain application DTO. Future domain relation adapter must preserve evidence, mapping version and HIL provenance. |
| `MeasureDefinition` | Versioned basis, grain, category, unit and inclusion rules | Retain application calculation contract, not a generic financial approval. |
| `MeasureInput` | Exact evidenced monetary/hour observation | Retain application input. Do not coerce into BOMLine or actual-cost data. |
| `CriterionAssessment` | Local gate requirement/applicability/evidence truth table | Retain now. Future `GateCriterionResult` may own reviewed domain semantics; use an explicit adapter, not a duplicate class or blind alias. |
| `DeliveryAcknowledgment` | Verified external receipt for exact product/attempt/destination | Retain application delivery DTO. A receipt is not a human GateDecision. |
| `AppliedTransition` | Ordered replay index into committed execution/decision history | Retain read model. Future StateTransition owns reviewed transition meaning; migration must not create two write authorities. |
| `CommittedExecutionRef` | Loaded execution integrity view | Retain read-only application view backed by canonical ProcessExecution and validated links. |
| `CommittedGateDecisionRef` | Loaded human decision integrity view | Retain read-only view; full decision remains future domain-owned. |
| `CommittedPolicyEvaluationRef` | Loaded automatic policy-evaluation integrity view | Retain read-only view. The separately stored evaluation is authoritative; a constructed ref is not proof of commitment. |
| `PublicSourceRecord` | Sanitized allowlisted ingress | Retain application boundary DTO; never accept raw ERP keys, part numbers or descriptions. |
| `RequirementClass`, `Applicability`, `EvidenceCondition`, `Result` | Gate truth-table literal vocabularies | Retain all four aliases. Migrate only with reviewed domain results and compatibility tests. |
| `aware` | Timezone-awareness guard | Retain helper. Compare shared guards before consolidation; preserve null-offset rejection. |
| `resume_action` | Pure extraction-reuse decision | Retain application helper. It is not the complete checkpoint validator. |
| `aggregate_measure` | Confirmed compatible-input summation/deduplication | Retain application calculation helper. |
| `replay_transitions` | Pure history-link/state/version validation | Retain application reader; never attach I/O or replay side effects. |

## Identity, request and reporting contracts

Project UUID -> logical-product UUID (configured output profile) -> run UUID -> immutable product/evaluation/graph identity+version -> independent delivery-attempt UUID -> verified document receipt. A project identity is not a source business number. Retry keeps request key/run; refresh creates a fresh key/run and new product version. Historical reproduction pins extraction inputs in a new run and does not automatically republish. HIL labels append events and create new evaluation/affected product/graph versions; do not edit earlier results. `latest_run` differs from `latest_published_version`; materialized projections do not mutate immutable payloads.

`GenerationRequest.fingerprint` hashes sorted compact ASCII JSON including schema version, canonical UUIDs, UTC-microsecond window bounds, calendar/version, mode, output/source profiles, mapping/calculation/policy versions and optional pinned manifest digest. Only request_key is excluded. Same key/same digest returns original run; same key/different digest conflicts before extraction/delivery. A different key deliberately creates a new run even for equivalent content. Receipt time, trace IDs and runtime-generated IDs are not behavioral inputs. Behavioral changes require new configuration versions; canonicalization cannot change silently.

Windows are half-open `[start, cutoff)`. `ReportCalendar.check_request` verifies calendar/version and local cutoff clock. Source occurrence/modification/receipt, processing, preparation and delivery acknowledgment are distinct times. Retain each SO/PO date's actual operational meaning; order/posting/fulfillment/receipt dates are not substitutes. Synthetic calendar: `America/Los_Angeles`, exclusive `06:00` cutoff. A known date-only input uses marked 09:00 Pacific fallback with seasonal offset, original_date and assigned precision. Unknown dates remain unknown; observed source timestamps stay unchanged. This fallback is not a measure inclusion rule. Resolve ambiguous/nonexistent live cutoff times explicitly; current checks are not a complete DST calendar policy.

## Measures and associations

Synthetic catalog `workflow-i-synthetic-measures/v1`:

| Measure | Unit / grain | Inclusion, duplicate rule and unavailable condition |
| --- | --- | --- |
| SO sell | Source currency / SO line | Evidenced amount, currency and confirmed project; exact source ID+version counted once. Changed content/version under one ID is ambiguity until reconciled. Missing amount/currency/coverage/association makes it unavailable. |
| PO ordered | Source currency / PO line | Same evidence/deduplication rule; keep order link, currency and date meaning. Never call ordered amount incurred cost or combine it with SO sell. Unsupported inputs make it unavailable. |
| Recorded labor | Hours / time entry | Evidenced hours and confirmed project; retain entry/version, period, classification/evidence. Never derive hours from sold lump sum. Unknown hours/assignment makes it unavailable. |
| Compatible category total | Source currency / project-category and one SO-sell OR PO-ordered basis | Sum compatible confirmed observations only, retaining every input and rule version. Mixed basis/currency/unit and ambiguous duplicates block. No compatible evidenced input means unavailable, not zero. |

Categories remain hourly internal labor, lump-sum internal labor, products, outsourced labor and integration materials. PO categories in the synthetic policy are products, outsourced labor and integration materials, not a classification of private records. Preserve original and proposed classifications separately; mappings are versioned/effective-dated with explicit exceptions. Skill does not select labor code. Mark unposted, provisional, late and corrected entries rather than silently dropping them. Actual incurred cost, margin, earned value and budget variance need separately verified sources/rules. Different currencies can coexist only in separately labeled series; recorded hours remain separate from money.

Explicit source links require exact typed endpoints, source version, independent evidence and project-membership validation. Reviewed mappings require version/effective scope and evidence; mapping is not financial approval. HIL confirmation requires actor, label event and exact candidate/evidence versions; applicability is reflected in a NEW evaluation/product. Unresolved candidates retain supporting/conflicting evidence and method version, appear in Symballion/Void gaps and never enter confirmed totals. A $1,000 PO line with two plausible projects stays an unallocated candidate, not $1,000 in each project. Conflicting evidence prevents confirmation. Neither contract nor subcontract follows from a numeric code; a confirmation label grants no accounting-write or gate authority.

## Gate truth table and publication policy

| Requirement / applicability | Evidence | Result | Transition effect |
| --- | --- | --- | --- |
| Mandatory or conditional / yes | Sufficient | Pass | Eligible for separate decision/policy, not approved by evaluation alone. |
| Mandatory or conditional / yes | Fails | Fail | Block. |
| Mandatory or conditional / yes | Missing/conflicting/stale | Corresponding result | Block. |
| Mandatory or conditional / unknown | Any | Missing | Block; never infer inapplicability. |
| Conditional / no | Any | Not applicable | Eligible with recorded rationale. |
| Mandatory / no | Any | Invalid definition | Reject, including at DTO boundary. |
| Informational / yes | Any | Corresponding result | Warn, never independently block. |
| Informational / no or unknown | Any | Not applicable or missing | Record gap, never independently block. |

`CriterionAssessment` checks local consistency; cross-record target/evidence/version validation remains separate. Evaluating a gate may finish with blocked criteria. Human GateDecision owns actor, bounded authority, scope, purpose, evaluation and exact target versions. Approval never silently carries to a new version/scope. Public Failure is an execution state, not a gate result.

Synthetic automatic publication checks immutable Prepared output, source/lineage reconciliation, private-data validation, compatible measures/no unresolved duplicates represented as confirmed, and configured synthetic destinations. Missing WBS, provisional data or uncertain attribution may publish only as faithfully labeled warnings, candidate queues and explicit coverage. The automatic policy is a **separately committed evaluation** recording run/product/policy/evidence versions and permit/block. `CommittedPolicyEvaluationRef` only reads that record. It grants no human authority and is not replaced by GateDecision. Published requires its matching permit plus verified receipts for **all configured required outputs**. Queue acceptance is insufficient. Production ClickUp operation/authorization remain unconfigured.

## History ownership and known integration gaps

- Canonical `ProcessExecution` owns what happened to objects. Reviewed workflow transition/domain state and full human decision records must be linked to that same execution and committed atomically with the new run version and outbox. `AppliedTransition` is an index, not a second authored event log.
- Canonical automatic evaluation commits against the prepared product BEFORE delivery. Verified delivery receipts then support a separate atomic Published transition. Rejection/rollback leaves no partially applied transition. Human-gated changes instead commit the scoped GateDecision with their transition.
- Full executions, decisions, evaluations, immutable products and checkpoints can use existing versioned aggregate persistence. Additional payload schemas/link lookups are required; the existing UoW has no dedicated P4 repositories. Do not invent methods on its ports or chain independently committing service calls and call that atomic.
- Current ProcessExecution has no `run_id`, `target: VersionRef` or `gate_decision_id` fields. Its incidence and reviewed P4 links must back CommittedExecutionRef; never treat caller-supplied refs as verified storage. GateDecision and StateTransition are still unimplemented scaffolds.
- Public state `In Process` contains a space; ProcessExecution's `StateName` forbids spaces. Proposed mapping: public `In Process` <-> internal `in_process`, with all five states explicitly mapped in a later reviewed adapter. Do not weaken the generic identifier contract or silently change API states.
- GenerationRequest.request_key allows 120 characters; persistence CommandRecord.command_id permits 80 safe identifier characters. Proposed mapping: fixed safe digest of a canonical, namespace/project/product-scoped key, retaining the full original key, scope and request fingerprint in a versioned admission payload. Lookup verifies all of them; collision/mismatch blocks. No truncation and no behavioral-fingerprint-only command key. This mapping is a proposal, not implemented policy.
- Current PublicSourceRecord has no source-version field, and string metadata in manifests/profiles is not automatically source-safe. Before live persistence, review an immutable per-record version/provenance envelope and opaque token/profile validation. No breaking field additions are made here.
- `replay_transitions` checks supplied references, legal edges and adjacency, not database commitment, complete human authority, required destination sets or baseline CAS. `resume_action` compares extraction context only; add full checkpoint/configuration validation outside it later.

Valid public edges remain Requested -> In Process/Failure; In Process -> Prepared/Failure; Prepared -> Published/Failure; Failure -> In Process only with a new auditable attempt. Published is terminal for that run. Reconstruct read-only, compare execution uniqueness, sequence, state/version adjacency and evidence/decision links with stored state; corruption blocks new transitions. Never re-run extraction, delivery or outbox during replay. Preserve suspicion, investigation, action, independent verification when configured, closure/reopening and evidence as distinct correction history. Planned milestone date, evidenced occurrence and sign-off are separate records. No automatic human review on every revision; explicit policy decides applicability of prior decisions.

## Migration and acceptance plan

1. **This checkpoint:** inventory and retain every existing symbol, add inventory-only registries/tests, specify boundaries and transactions. Preserve all accepted foundation cases and synthetic fixtures. No domain move, orchestration, port implementation, schema regeneration or production policy activation.
2. **After review:** approve/revise proposed state encoding, command-key mapping, source provenance envelope and ownership of future domain results/transitions. Review each deferred domain concept and minimum cross-phase dependency on its merits.
3. **Compatibility-first migration:** establish one canonical definition; leave old import paths as identity-preserving re-exports where compatible. A semantic/serialized-shape change requires a versioned DTO and explicit adapter, fixture/backfill/replay plan and negative tests, not a second same-named definition. Never make domain import application or infrastructure. Remove a compatibility path only with explicit follow-up approval.
4. **Persistence and conformance:** implement reviewed payloads/ports using existing UoW/CAS, source/destination conformance and immutable checkpointing. Prove competing admission, rollback, crash windows, full-history reload and destination reconciliation before orchestration.
5. **Orchestration then HTTP:** integrate only after the review checkpoint. Register generated schemas/OpenAPI with existing generators when real contracts/routes exist; update traceability using executable evidence. Run focused, full synthetic, release, PostgreSQL and messaging gates and state exactly which environments ran.

### Review checkpoint before orchestration

Confirm the reuse map and inventory; canonical execution/transition/human-vs-automatic decision ownership; proposed compatibility and key/state/provenance adapters; delivery timeout reconciliation and latest-published CAS rules; unresolved production configuration. Architecture scope approval is not approval of every proposed contract migration or live publication authority. This change deliberately stops here.
