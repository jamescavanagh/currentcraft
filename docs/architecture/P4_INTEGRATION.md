# P4 integration, transaction and recovery plan

Status: **planned integration only; stop at contract-review checkpoint**. This document does not add runtime handlers, persistence schemas, routes or external delivery. [P4 design contracts](../domain/P4_DESIGN_CONTRACTS.md) owns the reuse/migration decisions; [source adapter boundary](SOURCE_ADAPTER_BOUNDARY.md) owns private/public exchange.

## Existing mechanisms versus missing work

Reuse UnitOfWork, AggregateRepository/VersionedRecord, CommandLog/CommandRecord and OutboxRepository/EventEnvelope. One UoW is one database transaction; CAS conflicts reload and retry, never overwrite. Existing save_aggregate and run_once each open/commit their own UoW: calling them sequentially cannot implement an atomic multi-record P4 transition. Future P4 use cases must perform all related repository operations inside one shared UoW and commit once.

There are no P4-specific repositories, prepared checkpoint schemas, full GateDecision/StateTransition implementations or verified-reference loaders yet. Proposed record categories below are payloads over existing aggregate persistence, not new parallel logs or claims about existing port methods. Versioned aggregate heads alone are not a complete historical-reference resolver; use/validate history for exact versions and add narrowly reviewed query support only if needed.

## Write authority

| Record / view | Owner and rule |
| --- | --- |
| ProcessExecution | Canonical execution provenance. Persist once; workflow links refer to that execution, not a copied second execution. |
| Reviewed workflow run / StateTransition | Run aggregate owns state/version; transition records exact edge, execution and decision/evaluation links. Same transaction as execution/run/outbox. |
| Human GateDecision | Full scoped human decision: actor, authority/evidence, purpose, evaluation and target versions; same transaction as its controlled transition. |
| Automatic policy evaluation | Separate immutable committed permit/block record for exact prepared product, policy and evidence versions, committed before external delivery. Never masquerades as human approval. |
| AppliedTransition / Committed*Ref | Read-only indexes/views reconstructed from verified committed canonical records. They do not independently authorize writes or prove commitment. |
| Extraction / prepared checkpoint | Immutable public-safe inputs, intermediate outputs, configuration versions and digests. No raw source data or private handles. |
| Delivery intent / attempt / receipt | Durable append-only intent and outcome evidence across external calls. Unknown outcome is not a rejection or an acknowledgment. |
| Latest-published pointer | CAS-protected logical-product publication head; previous acknowledged product, distinct from latest requested/attempted run. |
| Outbox | Same-transaction effect intent, relayed after commit; not canonical workflow state or delivery receipt. |

Existing ProcessExecution lacks P4 run_id/target/gate_decision_id fields. Future loaders must join/validate reviewed transition and incidence links to build CommittedExecutionRef. Public `In Process` also conflicts with process StateName's no-space pattern. Resolve the explicit mapping proposed in the design before writing a workflow adapter.

## Execution sequence and transaction boundaries

### T0: admit command and requested run

Validate calendar, window, configured profiles/versions and fingerprint before any I/O. Resolve the request key to a safe command identity using the reviewed mapping. Existing 120-character request keys cannot be written directly to the 80-character persistence identifier. Store original key, scoped identity and fingerprint in a versioned admission payload using existing aggregate storage; CommandRecord references the admitted outcome, not a second command ledger.

Inside one UoW, verify existing admission: same scoped key+fingerprint returns original run; changed fingerprint or collision rejects without extraction or delivery. For a new admission, persist the requested run, admission payload, command outcome and any corresponding outbox in the same commit. Competing admissions must have a single winner through existing uniqueness/CAS with tested conflict reload. Do not rely on a check-then-write race or use run_once unchanged: its prior-outcome shortcut does not compare fingerprints. Rejected conflicting retries must not replace the original admission record.

### T1: start auditable execution

Reload run/version and verify committed history before advancing. In one UoW commit canonical execution, linked Requested->In Process transition, next run version and outbox. A retry from Failure requires a new auditable attempt and legal Failure->In Process transition. Never reuse an execution ID for a different attempt.

### Outside transaction: extract and compute

Call configured source adapter/sanitizer without holding database locks across network I/O. Complete an immutable sanitized extraction and validate manifest, coverage, per-record provenance, measures, associations and lineage. Pin mapping/calculation/policy/calendar/profile versions. Compute candidate queues, warnings and graphs without promoting unresolved attribution into confirmed totals. Recheck cancellation/version/context before committing results.

### T2: prepared checkpoint and Prepared transition

In one UoW, CAS the run and persist immutable prepared product/evaluation/graph references, exact digests, complete extraction manifest/reference, checkpoint, execution, In Process->Prepared transition and outbox. Record the previous successfully acknowledged baseline used for the delta. Intermediate content-addressed writes outside the transaction are acceptable only when immutable, verified and unreachable from committed state until this commit; orphan cleanup is not an applied transition.

### T3: automatic evaluation commit

Evaluate the named versioned synthetic publication policy against exact committed prepared payload, source/lineage, private-data validation, compatible measures and required-output configuration. In one UoW record the full immutable evaluation, target/run/policy and versioned evidence with permit/block outcome. A later reader constructs CommittedPolicyEvaluationRef from storage. Block leaves the product unpublished; it is not automatically a human rejection or Failure transition. A full human-gated use case instead requires a scoped GateDecision in its own controlled transition transaction.

### T4: delivery intent, then external effect

After revalidating prepared context and permitted evaluation, commit stable delivery intent/attempt, required output identity, product digest and destination-profile version BEFORE any external call. Call destination outside the UoW. Use/reconcile that identity on retry. Never create another document merely because the caller timed out. A definitive safe rejection and an unknown outcome have different recovery paths.

### T5: persist verified receipts

Verify exact attempt, product/version, output and destination against configured completion semantics. Persist each immutable receipt/outcome durably; a receipt for a different version cannot complete this run. Unknown/pending/rejected outcomes cannot become DeliveryAcknowledgment. Successful individual receipts survive a failure to deliver another required output. Current AppliedTransition has a single delivery_ack field; future checkpoint/receipt-set contracts must retain all required output receipts and identify the selected reference without silently changing this accepted DTO.

### T6: Published transition and baseline advancement

In one UoW reload prepared run, exact permitted evaluation and complete verified required receipt set; verify stored product/output digests, history and expected run/publication-head versions. Commit canonical execution, linked Prepared->Published transition, next run version, monotone latest-published pointer and outbox together. No publish-before-receipt shortcut. A crash after receipt persistence but before T6 resumes T6 without another external create.

Required concurrency rule: an older run cannot move the publication pointer backward. Delta output pins its acknowledged predecessor. If another run advances that predecessor while this run computes/delivers, block stale finalization and investigate/reconcile; do not silently promote an artifact whose delta used the wrong base. External artifacts already created remain visible delivery history, not an excuse to overwrite immutable Prepared output. The later implementation must choose/test a per-product delivery serialization mechanism or explicit superseded-delivery handling; the existing UoW alone cannot lock an external system. Product ordering/expected-predecessor semantics require reviewed payloads before implementation.

### After commit: relay

Relay existing outbox events after each committed change. Duplicate transport events are expected; consumers deduplicate by event identity/version. A relay failure does not roll back an already committed transition. No broker receipt sets Published. Read-only history replay never invokes adapters or relays outbox.

## Prepared checkpoint minimum (future versioned payload)

- Run/project/logical-product identities, request key scope/fingerprint, expected run version and stage/attempt identity.
- Complete sanitized extraction manifest and exact immutable bytes/reference/digest, source contract/profile/capability and opaque token handle.
- Exact calendar/window/cutoff, mapping/calculation/policy/output/source/destination configuration versions; required output identities.
- Prepared product/evaluation/graph and intermediate output references/digests, source-version evidence links, warnings/coverage and private-data validation evidence.
- Exact previously acknowledged baseline product/version, publication-head version/order context and true comparison interval.
- Committed automatic evaluation reference and, as delivery progresses, stable attempt identities plus verified receipt references or explicit unknown outcomes.

Checkpoint updates append versions; never mutate an earlier checkpoint/product. resume_action validates only extraction compatibility. Full resume must also compare every pinned behavioral configuration, output digest, stage/run version, history and baseline. A refetch/recompute must occur in a legal new attempt/run context; never replace the bytes of an already Prepared product. Reproduction uses pinned inputs in a new run and does not implicitly deliver.

## Recovery matrix

| Failure / interruption | Required recovery |
| --- | --- |
| Same scoped key, different fingerprint | Conflict; no extraction/delivery; retain original outcome. |
| UoW failure or CAS conflict | Entire transaction rolls back; reload canonical history/context before retry. No partial transition. |
| Incomplete pages or changed context/capability | Block assembly/reuse. Missing rows do not prove removal. |
| Changed snapshot/change token | Full refetch and recomputation in legal attempt context; never stitch pages. Same token with changed bytes is a consistency violation and blocks. |
| Best-effort source resumed | Only exact complete pinned extraction can be reused. New extraction identity/digest cannot be merged. |
| Prepared commit succeeded, worker crashed | Load/verify immutable checkpoint and continue evaluation/delivery; no new extraction just to replay. |
| Committed policy blocks or mismatches target | No delivery; preserve evaluation evidence. Human approval is not a substitute for this automatic policy. |
| Intent committed, call not made | Reconcile status before first/repeated write; use same identity. |
| Timeout / lost receipt / crash after external write | Outcome unknown. Query/reconcile stable delivery identity. If destination cannot disambiguate, block for investigation, do not blindly create. |
| Some required outputs acknowledged | Retain receipts, reconcile remaining attempts; do not publish until the configured complete set verifies. |
| Receipts committed, Published commit failed | Resume T6 with same exact references after CAS/history/baseline checks, not another create. |
| Concurrent newer publication | Prevent baseline regression; stale delta/delivery requires explicit reconciliation or fresh run. |
| Corrupt/gapped execution, decision or version links | Block further transitions and investigate. Do not repair history by replaying effects. |
| Outbox relay failure | Retry committed pending entries; consumer deduplication handles repeat delivery. |

First publication is a baseline, not all changes happening that day. Missed runs widen the actual delta interval. Retain source event time AND first observed time so newly seen backdated entries are labeled. Best-effort or partial coverage may warn only under a versioned policy that describes population honestly; misleading removals/deltas block.

## Acceptance and stop line

Before orchestration: review ownership/reuse map, proposed state/key mappings, per-record provenance and multi-output checkpoint/receipt contracts. Then demonstrate rollback across all records, competing request admission/publication CAS, exact-version loading, corrupt-history rejection, output-set validation and every recovery row with synthetic conformance tests. Keep all accepted foundation tests. Run the full synthetic/release suites; separately report actual PostgreSQL 18 and NATS tests rather than treating stand-ins as production proof. No real destination, accounting rule, source adapter or authority is configured here.
