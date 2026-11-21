# P4 design contracts and migration checkpoint

Status: **reviewable domain-contract implementation; no orchestration, operating grant or production publication**. PR #4 established the application DTO foundation; PR #5 established the architecture checkpoint. This domain batch starts at `25b1aec94ab8e1402b7a9fc22f166ae84e5349ba`. James's superseding P4 requirements govern business meaning. This page owns the design and reuse decisions; application contracts remain at their existing paths except the identity-preserving VersionRef re-export described below.

Companion specifications:
- [Source/destination boundary](../architecture/SOURCE_ADAPTER_BOUNDARY.md): public contracts, sanitization and private composition.
- [P4 integration plan](../architecture/P4_INTEGRATION.md): transaction sequence, checkpoints, delivery and recovery.
- [Persistence](../architecture/PERSISTENCE.md): existing repository/UoW guarantees and verification limits.

## Provenance and limits

- **James requirement:** Workflow I runs are workflow subjects; refresh creates a new run; five public states; automatic publication after integrity checks; Published only after destination acknowledgment; warnings for honestly represented gaps; collision and double counting block; previous successfully published version is the delta baseline; no private Acumatica or part references in the public repository.
- **Developer encoding:** UUID identities, per-aggregate monotone versions, pinned inputs, SHA-256 canonical request fingerprints, committed process/transition/decision links, explicit gate results and allowlisted ingress. These remain reviewable technical proposals, not production policy.
- **Synthetic only:** `workflow-i-synthetic-publication/v1`, `workflow-i-synthetic-calendar/v1`, synthetic source/destination and opaque IDs. No KCM accounting or operating authority follows.
- **Unresolved production configuration:** destination operation/location and completion semantics; source-safe labels; reporting cutoff; real adapter capabilities; accounting mappings; authorization/access control; accepted live measure definitions.
- The 17 P4 domain concepts now implement local and explicit-context invariants as `p4-proposal`, not semantic acceptance or durable execution. Historical imports are preserved, but empty scaffold construction is deliberately replaced with required identity/contract fields. No runtime/HTTP completion or traceability completion is claimed.

## Canonical reuse map

| Concern | Existing owner | Decision / boundary |
| --- | --- | --- |
| Shared identity, facts and evidence | `app.domain.shared.identity`, `facts`, `app.domain.quality.quality_evidence`, `app.domain.versioning` | Reuse opaque identity, Fact/evidence capture and VersionedEntity. Correction to PR #5: versioning is at domain/versioning.py, not a pre-existing shared/versioning.py. Preserve historical limitations and independent reference verification. |
| Exact version reference | New `app.domain.shared.versioning.VersionRef` | Single definition migrated from PR #4 without field/config/JSON shape change; old application import is the same class via re-export. P4Record extends existing VersionedEntity, not a parallel entity store. |
| Process provenance | `app.application.process.contracts.ProcessExecution`, `ObjectIncidence`, `CapabilityBinding`, `AuthorityRef`; `lifecycle.derive_object_events` | One canonical execution per applied transition. Objects are things; resources execute. Derived object events are not a second authored history. `decision=release/hold/reject/return` is an effect, not a lifecycle state or sufficient authorization. |
| Workflow state / transition | `app.domain.workflow` definitions/records; application `AppliedTransition` | Domain owns version-pinned semantics. P4 index remains a read view, not a second independently writable transition log. Persisting and loading canonical history is deferred. |
| Human gate decisions | `app.domain.quality.GateDecision`; current `CommittedGateDecisionRef` | Full record captures actor, bounded scope/purpose, authority evidence, evaluation, transition and target versions. Domain checks context; application must resolve current authority/evidence and storage commitment. Ref is not an approval. |
| Persistence | `VersionedRecord`, `AggregateRepository`, `CommandRecord`, `CommandLog`, `UnitOfWork` | Store reviewed P4 payloads using existing aggregate history and CAS. Add no parallel command/event database. Existing records do not implement P4 checkpoint or request-fingerprint semantics by themselves. |
| Command replay | `app.application.persistence.services.run_once` | Retain general behavior; do not use unchanged for P4 admission: it returns prior outcomes without comparing request content. Validate P4 fingerprint before returning prior run. |
| Outbox / broker | `app.application.messaging.EventEnvelope`; UoW outbox and `relay_outbox` | Commit with changes, relay after commit; at-least-once effects need deduplication. Broker acknowledgment is not destination receipt. |
| HTTP composition | `app.interfaces.http` app/container/wiring | Inject configured adapters through composition root later. No synthetic fallback for unconfigured live integration. |
| Cross-phase concepts | `data_governance.data_product`, `data_lineage`, `commercial.cost_code` | Still scaffolds; review minimum dependencies explicitly. Do not mark later phases complete. |
| Commercial identities | `commercial.commercial_order.Order`, `Contract`, `materials.bom_line` | Reuse Order; source line is not implicitly BOMLine. Contract means company/client; subcontracts belong to other stakeholders. No NLP extraction here. |
| Schemas / docs | Existing generators and scaffold tests | Regenerate scaffold reference with distinct p4-proposal status. Application CONTRACTS remains inventory, not schema/OpenAPI registration. Never hand edit generated files. |
| Private integrations | Private Acumatica adapter, crosswalks, credentials and destination wiring | Stay outside public packaging. Public conformance uses synthetic records/destinations only. |

Dependency order: reviewed contracts/domain decisions -> source/destination ports -> persistence/checkpoints -> measures/graphs -> delivery acknowledgment -> HTTP. `docs/ROADMAP.md` is historically stale; it cannot override superseding P4 brief.

## Complete existing application-contract inventory

All names retain their existing application import path. Only VersionRef has moved physically; it is re-exported as the identical class. Other fields, defaults, validators, serialization, fingerprints and function signatures are unchanged. CONTRACTS still lists 15 payloads; support types, aliases and helpers have separate inventories, referencing definitions rather than copying them.

| Existing symbol | Current responsibility | Disposition |
| --- | --- | --- |
| `Frozen` | Frozen, extra-forbid validation base | Retain application support type. Do not silently substitute shared base configuration. |
| `VersionRef` | Immutable UUID/version reference | Migrated to domain/shared/versioning.py; compatibility re-export preserves strict positive version, hashability and JSON shape. |
| `WorkflowIIdentity` | Distinct project/product/run/evaluation/graph/attempt identities | Retain application composition DTO, not second workflow aggregate. |
| `ReportCalendar` | Versioned local cutoff/date-only fallback | Retain; production DST resolution remains prerequisite. |
| `GenerationRequest` | Admission, fingerprint/retry comparison | Retain; command-key mapping remains proposed. |
| `ExtractionManifest` | Extraction capability/completeness/digest | Retain; private snapshot handles cannot leak through strings. |
| `Association` | Candidate/confirmed relation evidence | Retain; future adapter must preserve mapping/HIL provenance. |
| `MeasureDefinition` | Versioned basis/grain/unit/inclusion rules | Retain application calculation contract, not financial approval. |
| `MeasureInput` | Exact evidenced money/hour observation | Retain; not BOMLine or actual-cost data. |
| `CriterionAssessment` | Local gate truth table | Retain PR #4 DTO; not an alias for version-pinned domain GateCriterionResult. Future explicit adapter required. |
| `DeliveryAcknowledgment` | Verified exact external receipt | Retain; not human GateDecision. |
| `AppliedTransition` | Ordered replay index | Retain application read model; domain StateTransition owns edge/execution/version semantics, not a second write authority. |
| `CommittedExecutionRef` | Loaded execution integrity view | Retain; application must verify canonical provenance and links. |
| `CommittedGateDecisionRef` | Loaded human decision integrity view | Retain read-only view of full domain record. |
| `CommittedPolicyEvaluationRef` | Loaded automatic evaluation integrity view | Retain; constructed ref is not commitment or permit proof. |
| `PublicSourceRecord` | Sanitized allowlisted ingress | Retain; no raw ERP keys, part numbers or descriptions. |
| `RequirementClass`, `Applicability`, `EvidenceCondition`, `Result` | Gate literal vocabularies | Retain four application aliases; no duplicate model definitions. |
| `aware` | Timezone-awareness guard | Retain application helper/null-offset rejection; domain guard serves domain models without reversing dependencies. |
| `resume_action` | Pure extraction reuse | Retain; not full checkpoint validator. |
| `aggregate_measure` | Confirmed compatible-input summation | Retain. |
| `replay_transitions` | Pure reference/state/version validation | Retain; no I/O or replay effects. |

## Identity, request and reporting contracts

Project UUID -> logical-product UUID (configured output profile) -> run UUID -> immutable product/evaluation/graph identity+version -> independent attempt UUID -> verified document receipt. Project identity is not source business number. Retry keeps key/run; refresh gets fresh key/run and new product version. Reproduction pins extraction in a new run and does not automatically republish. HIL labels append events and new evaluation/product/graph versions, never edit earlier decisions. latest_run differs from latest_published_version; projections do not mutate immutable payloads.

GenerationRequest fingerprint hashes sorted compact ASCII JSON with schema version, canonical UUIDs, UTC-microsecond windows, calendar/version, mode, output/source profiles, mapping/calculation/policy versions and pinned manifest digest when supplied. Only request_key is excluded. Same key/same digest returns original run; same key/different digest conflicts before I/O. Different key deliberately creates a new run even for equivalent content. Receipt time, trace IDs and generated runtime IDs are not behavioral inputs. Behavioral changes require new configuration versions; canonicalization cannot change silently.

Windows are half-open `[start, cutoff)`. ReportCalendar.check_request verifies calendar/version and local clock. Source occurrence/modification/receipt, processing, preparation and acknowledgment are distinct times. Preserve each SO/PO date's actual order/posting/fulfillment/receipt meaning. Synthetic calendar: America/Los_Angeles, exclusive 06:00 cutoff; known date-only inputs use marked 09:00 Pacific fallback with seasonal offset, original_date and assigned precision. Unknown remains unknown; observed timestamps stay unchanged. Fallback is not an inclusion rule. Resolve ambiguous/nonexistent live cutoffs explicitly; current checks are not full DST policy.

## Measures and associations

Synthetic catalog workflow-i-synthetic-measures/v1:

| Measure | Unit / grain | Inclusion, duplicate rule and unavailable condition |
| --- | --- | --- |
| SO sell | Source currency / SO line | Evidenced amount/currency/confirmed project; exact source ID+version counted once. Changed content/version under one ID is ambiguity until reconciled. Missing amount/currency/coverage/association makes unavailable. |
| PO ordered | Source currency / PO line | Same evidence/deduplication; retain order link/currency/date meaning. Never call ordered amount incurred cost or combine with SO sell. Unsupported input makes unavailable. |
| Recorded labor | Hours / time entry | Evidenced hours/project, entry/version/period/classification/evidence. Never derive hours from sold lump sum. Unknown hours/assignment makes unavailable. |
| Compatible category total | Source currency / project-category, one SO-sell OR PO-ordered basis | Sum compatible confirmed observations with all inputs/rule version. Mixed basis/currency/unit and ambiguous duplicates block. No compatible input means unavailable, not zero. |

Categories remain hourly internal labor, lump-sum internal labor, products, outsourced labor and integration materials. Synthetic PO categories are products, outsourced labor/integration materials, not classification of private records. Preserve original/proposed classifications separately, versioned effective-dated mappings and exceptions. Skill does not select labor code. Mark unposted/provisional/late/corrected entries rather than discarding. Actual incurred cost, margin, earned value and budget variance require separately verified sources/rules. Different currencies coexist only in labeled separate series; hours remain separate from money.

Explicit source links require typed endpoints, source version, independent evidence/project membership. Reviewed mappings require version/effective scope/evidence; mapping is not financial approval. HIL confirmation requires actor, label event and exact candidate/evidence versions in a NEW evaluation/product. Unresolved candidates retain supporting/conflicting evidence/method version, appear in Symballion/Void gaps and never enter confirmed totals. A $1,000 PO line with two plausible projects remains unallocated, not $1,000 in each. Conflicting evidence blocks confirmation. Neither contract nor subcontract follows from numeric code; confirmation grants no accounting-write/gate authority.

## Gate truth table and publication policy

| Requirement / applicability | Evidence | Result | Effect |
| --- | --- | --- | --- |
| Mandatory or conditional / yes | Sufficient | Pass | Eligible for separate decision/policy, not approved. |
| Mandatory or conditional / yes | Fails | Fail | Block. |
| Mandatory or conditional / yes | Missing/conflicting/stale | Corresponding result | Block. |
| Mandatory or conditional / unknown | Any | Missing | Block; never infer inapplicability. |
| Conditional / no | Any | Not applicable | Eligible with rationale. |
| Mandatory / no | Any | Invalid definition | Reject in definition-context validation. |
| Informational / yes | Any | Corresponding result | Warn, not independently blocking. |
| Informational / no or unknown | Any | Not applicable or missing | Record gap, not independently blocking. |

CriterionAssessment retains its original local check. Domain GateCriterionResult pins definition/target/evidence versions and checks local truth. `blocks(definition)` rejects mandatory inapplicability using exact definition. QualityGateInstance.passes checks complete criterion-version coverage and target/time consistency; evaluation may complete while blocking. These explicit context methods must be called with loaded exact records; constructor validation alone does not resolve references.

Human GateDecision captures actor, effect/scope/purpose, authority evidence, execution, evaluation and transition versions. validate_context checks matching human gate and target, evaluation timing, blocking criteria and required distinct-actor quorums using scoped, unexpired approvals. Scope/role/actor constraints are checked; existence, trust, validity/revocation of authority/evidence and access control MUST be independently resolved by future application services. An approval cannot silently carry to another target/evaluation/version/purpose. Public Failure is an execution state, not gate result.

Synthetic automatic publication uses immutable Prepared output, source/lineage reconciliation, private-data validation, compatible measures/no unresolved duplicates counted as confirmed, and configured synthetic destinations. Missing WBS/provisional data/uncertain attribution may publish only as faithful warnings, candidates and explicit coverage. Automatic evaluation is separately committed with exact run/product/policy/evidence and permit/block; CommittedPolicyEvaluationRef only reads it. It grants no human authority and cannot be replaced by GateDecision. Published still needs matching permit and verified receipts for ALL required outputs. Queue acceptance is insufficient; production ClickUp operation/authority remain unconfigured.

## Implemented domain semantics and migration

- Six definitions: LifecycleState uses process-safe code and separate display label; TransitionDefinition separates none/human_gate/automatic_policy and retry-attempt requirement; WorkflowDefinition checks exact state versions, uniqueness, initial/terminal topology and reachability. GateCriterionDefinition pins predicate/applicability rule; GateApprovalRequirement defines scope, purpose, role, actor set, quorum and optional independence; QualityGateDefinition pins criteria/requirements and does not contain automatic publication policy.
- Six execution/evaluation records: WorkflowInstance pins definition/target/state and transition history reference; GateCriterionResult/QualityGateInstance pin definition, target, evidence and evaluation coverage; Approval/GateDecision model scoped human responses/control effects; StateTransition pins workflow/edge/state/target/execution and mutually exclusive human-decision or automatic-evaluation links. Its validate_context checks links/adjacent workflow versions, not durable commitment or automatic permit/receipt truth. Required automatic permit loading remains deferred.
- Five correction/milestone records: Nonconformity versions suspicion/investigation/confirmation/closure/reopening and validates predecessor adjacency/legal edges. CorrectiveAction separates implemented snapshot from later verification/closure, pins implementation actor/time/evidence and optional independence policy. VerificationActivity pins exact implementation/target; validate_verifications loads that snapshot, rejects context drift and failed/missing verification for closure. Application must additionally load referenced nonconformities/evidence and validate complete correction histories.
- Milestone planned_date, evidenced occurred_at and MilestoneSignOff are distinct. Sign-off requires scoped human approval against exact occurrence version, actual occurrence before signature and correct authority requirement. A single sign-off cannot satisfy a multi-person quorum; that requires future aggregate handling, not silently counting one actor twice.
- VersionRef is now defined once in domain/shared/versioning.py and re-exported at app.application.p4.contracts.VersionRef. Existing serialized fields/config and hashability are retained; Python module ownership changes and code relying on Frozen subclass identity must migrate explicitly. Other application DTOs are not aliased to semantically different domain records. PR #4/#5 foundation tests remain and compatibility tests cover class identity and schema shape.
- P4Record reuses existing domain/versioning.VersionedEntity, preserving opaque entity IDs, strict record versions, external/evidence capture and deterministic construction. p4-proposal status/schema distinguishes implemented proposed semantics from V1 capture; it is never an operating approval. Historical scaffold imports remain, but zero-argument construction deliberately fails. Existing manifest names/count remain unchanged; generated reference and compatibility gate recognize the new status.

## History ownership and unresolved integration gaps

Canonical ProcessExecution owns what happened. Domain StateTransition and human decision must link to the same execution and commit atomically with run version/outbox. AppliedTransition is a read index, not a second log. Automatic evaluation commits against Prepared product BEFORE delivery; verified receipts support separate Published commit. Rejection/rollback leaves no partial transition. Full payloads use existing VersionedRecord/UoW; P4-specific payload loaders/checkpoints and query support remain to implement. Do not invent existing port methods or chain independent committing services and call them atomic.

ProcessExecution lacks run_id/target VersionRef/gate_decision_id; future loaders validate incidence and P4 links. Domain safe codes support in_process with public display In Process, but executable application mapping is deferred. GenerationRequest permits 120-character keys; CommandRecord permits 80 safe characters. Proposed safe digest of canonical namespace/project/product-scoped key retains full original key/scope/fingerprint in versioned admission payload. Verify all on lookup; collision/mismatch blocks, no truncation or behavioral-fingerprint-only command key. Not implemented here.

PublicSourceRecord still lacks source-version field; string metadata is not inherently safe. Review immutable per-record provenance envelope and opaque token/profile validation before live persistence. replay_transitions checks supplied refs/edges/adjacency, not storage commitment, full authority, required output sets or baseline CAS. resume_action compares extraction context only; full checkpoint validation remains future work. See boundary/integration companion documents for unchanged transaction/recovery requirements; their pre-domain status statements are historical until integration is implemented.

Valid Workflow I public edges remain Requested -> In Process/Failure; In Process -> Prepared/Failure; Prepared -> Published/Failure; Failure -> In Process with new auditable attempt; Published terminal. Generic definitions intentionally support other workflows; future Workflow I composition must supply exactly this profile. Reconstruct read-only and compare sequence/execution uniqueness/state/version/evidence links; corruption blocks transitions. Never rerun extraction/delivery/outbox during replay. No automatic human review every revision; explicit policy evaluates prior-decision applicability. Suspicion, investigation, action, verification, closure/reopening and evidence remain distinct history.

## Next acceptance checkpoints

1. Review implemented domain semantics and migration tests before merging. No orchestration, port implementation, production activation, or claim of completed authority resolution.
2. Implement minimum CostCode/DataLineage/DataProduct dependencies and public contracts/ports with explicit application DTO adapters/migration. Synthetic adapter conformance precedes any real private integration.
3. Implement persistence/checkpoints using existing UoW/CAS. Prove admission conflicts, rollback, exact-version loading, corrupt-history rejection, delivery reconciliation and stale-publication handling before orchestration.
4. Integrate measures/graphs/deltas using previous successfully acknowledged baseline, not latest run. First report is baseline; missed runs widen comparison interval; retain source event/first-observed times for backdated entries. Incomplete extraction never proves removal. Warn only when versioned policy faithfully describes coverage; misleading deltas block.
5. Register schemas/OpenAPI using existing generators when public commands/routes exist; update traceability only with executable evidence. Report actual focused/full/release/PostgreSQL/messaging environments separately. Local domain tests do not certify persistence, hosted CI or production operation.
