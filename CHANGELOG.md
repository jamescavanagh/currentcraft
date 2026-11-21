# Unreleased: drawing lifecycle design correction (docs only)

- Implemented in documentation only: superseded the earlier facet proposal with the accepted requirement that Drawing is separate from Document and Revision and Submittal are Document subtypes. Historical proposal retained; Decision 4 source-file never-lock rules unchanged.
- Added option 2 controlled-release design with described proposed fields, exact-native-revision rendition and acknowledgment, separate authorization/sending/acknowledgment/PM visibility evidence, and clearance of only the drawing prerequisite.
- Not implemented or claimed: lifecycle contracts, workflow execution, operational authority/recipient/escalation policy, installation readiness, or completion of 0.11.0. Drawing-revision type composition remains undecided; work-package-specific release is deferred.
- Phase 2 requires the 0.10.0 read-endpoints PR #25 merge and separate coordinator go-ahead. Package/runtime version remains 0.9.9 because this slice changes design documents only; no generated contracts or runtime files changed.

# Unreleased: scoped local API integration

- Added a separate Compose API service with loopback-only host publishing, bootstrap completion dependency, shared blob storage, readiness healthcheck and the API installation extra. The API and its new secret-provisioning helper both start as UID/GID 10001 with all capabilities dropped and no-new-privileges; the earlier privileged API staging design is replaced.
- Local initialization exclusively generates and retains a 64-hex API token with owner-only host permissions. The host streams three validated secrets over stdin to the nonroot provisioner, which installs mode-0400 files in a UID-10001-owned mode-0700 named volume initialized by the image at build time. The API mounts it read-only; no host secret mounts, root helper, secret argv/environment values, or world-readable API token workaround. Provisioning failure blocks launch. Existing database, broker, data-volume and persisted object identities are unchanged.
- Local launch configuration prefers `CURRENTCRAFT_*`; `DATAMESH_*` remains a fallback for one release. Explicit preferred values win. A runtime bridge leaves HTTP and ingestion implementation paths unchanged.
- Added bounded liveness/readiness and positive/negative shared-token shell smoke to `smoke`, plus standalone `api-smoke`. Existing worker smoke remains intact.
- Not claimed: whole-stack rootlessness (the existing root prepare service is unchanged), Docker daemon rootless mode, POST-and-poll intake smoke, repository-wide rename, or a 0.10.0 release/version bump. The prior revision's Docker shell-smoke timeout is not evidence of this revision passing; Docker/Actions and live-service results must be reported separately from static checks.

# 0.9.9 (2026-11-16)

- **HFGT capability graph (`datamesh-hfgt/v1`, new).** `app.application.hfgt` translates process-first records into hetero-functional graph theory (Farid, Thompson & Schoonenberg 2022): resources, buffers, operands (`kind:state`), transformation and refined transport processes, capabilities. `NumpyHfgtGraphAdapter` builds M-/M+, `A_rho = M+^T M-`, K_S masking (`mask` or `drop`), readiness (`reachable`, `blocked: constraints`, `unknown: translation gaps`, `unreachable`), dead ends, and a PyG-style `CapabilityGraphSample` (x N x 12, edge_index, edge_attr E x 5, edge_type by input-operand-set layer, candidate edges kept apart). Readiness is a structural reading, never a release.
- **Gaps are reported, never guessed.** Missing buffers, undeclared buffers, missing `state_before`, `exchange`, unknown executors and non-computed executions become `TranslationGap`s; an execution with any bad incidence yields no partial capability. Documented deviations from the paper ship in every report.
- **Golden fixtures and oracle.** `scripts/hfgt_reference.py` (standalone numpy) produced `tests/fixtures/hfgt/*.expected.json` from two synthetic WME rack fixtures. Baseline 10 capabilities / 12 sequences reachable; truck cannot carry rack 9 / 8 blocked; builder unavailable 9 / 8 blocked; gaps fixture 8 / 7 unknown. The adapter refuses any A_rho that differs from the paper's five-rule construction. Synthetic: proves the translation, not a real process.
- **Process contract (additive, still `datamesh-process/v1`).** Optional `ProcessExecution.at_buffer`, `ObjectIncidence.origin_buffer` / `destination_buffer` (transfers only, both or neither). 0.9.8 payloads validate unchanged; ingestion projections are byte-identical.
- **Simulation digests are node-order independent** (harness row M07). Nodes are sorted by id when a request is validated, so digests and tensor row order (`node_ids`, coupling, `GraphSample.x`) no longer depend on input order. Requests whose nodes were already in id order keep their digest; others get a new one. Regression test with two collision events.
- **Shared base moved.** `_Frozen` now lives in `app.application.common.contracts` (re-exported from `simulation.contracts` for one release). The splice layering test now also forbids the simulator; new tests keep `common` slice-free and hfgt to tensor descriptors only.
- `ParticipationEdge.resource_id` description fixed: a participating resource, never an operand.
- Test flake fixed: the synthetic XLSX builder wrote wall-clock zip timestamps, so two workbooks built across a 2-second boundary differed and `test_reingest_is_idempotent` failed about 1 run in 20. Entries now use a fixed timestamp. Test-only; adapters unchanged.
- Release allowlist: `src/app/application/common/`, `src/app/application/hfgt/`, `src/app/infrastructure/hfgt/`, `tests/fixtures/**/*.json`.
- **Not in 0.9.9 (see `docs/ROADMAP.md`):** the GNN encoder implementation, content embedding columns, moving tensor descriptors to `common`, the open SME and reviewer decisions, real-record HFGT runs, and the 0.10.0 FastAPI document API, now rebased on 0.9.9.

# 0.9.8 (2026-11-14)

- **Eigenvalues are mu; lambda means inflow only.** `CriticalPoint.lambda_min_abs` is now `mu_min_abs` (smallest |eigenvalue| of the Jacobian, saddles only). Kernel `critical_points` emits `mu_min_abs`; the adapter maps it through. No numerical change: same formula, same values.
- **Simulation schema `datamesh-sim/v1` -> `datamesh-sim/v2`**, because renaming an output key is a breaking change under the contract rule. v1 payloads still read: `schema_version` v1 is upgraded on input and `lambda_min_abs` is accepted as a deprecated alias; a payload carrying both keys is rejected as ambiguous. Output is always v2 with `mu_min_abs`.
- Consequence: request digests include `schema_version`, so every simulation request digest changes. Results computed under v1 keep their recorded v1 digest; re-reading their request yields the v2 digest. Re-run, do not rewrite, anything keyed by the old digest.
- Not renamed, on purpose: gauge/probe patch eigenvalues (`lambda2 / lambda3` planarity, `lam` in `lattice_kernels.patches`) live outside the simulator, where lambda is not inflow; chamber `lam` (barrier lowering per ion load) is not an eigenvalue.
- Tests: 8 new (`tests/test_eigenvalue_naming.py`): kernel key, contract field, legacy read and write-back, ambiguity rejection, v1 upgrade with digest equality, unknown version rejection, no eigenvalue `lambda_min_abs` left in simulation sources or generated docs.
- Generated simulation contract docs carry the notation and legacy-read note. Private references unchanged and still shipped under git-ignored `references/private/`.

# 0.9.7 (2026-11-12)

- **Sparse phase splice** (`app.application.splice`, `app.infrastructure.splice`), design source `docs/pipelines/SPARSE_PHASE_SPLICE.md`. Couples workbook source occurrences to a phase-blocked sparse embedding space with declared, versioned phase parameters.
  - `PhaseChart`: anchors per phase code, origin, direction, bins, von Mises concentration, sparsity floor, shared weight and required provenance. A research coordinate for similarity weighting, never the simulator plate phase.
  - Phase evidence by declared rule only: a field, one typed relation hop to a field-phased target, or positive per-phase hours. Blank and zero are never evidence; unanchored codes are reported, not guessed; no phase from row order or titles.
  - Space: block 0 phase-free, block 1+b per bin; same signed blake2b hash as the ingest tensorizer; slot tokens for declared fields and non-provenance relation types (never targets). Cosine factorises exactly as content x coupling; unit norm; zero-based indices persisted through the existing pgvector `sparsevec` conversion. Profile digest (chart included) pins `EmbeddingSpace.model_version`, so a parameter change is a new space.
  - Junctions: cross-phase candidates with content similarity, phase coupling, spliced similarity, chart distance and shared words; kind filter, content threshold, minimum shared words and cap. Always `candidate`; no relation, dependency, approval or allocation is written.
  - `store_splice` persists the sparse records in one unit of work. No messaging events and no write to the probe or plate.
- Tests: 26 synthetic splice tests (analytic chart controls, evidence rules, factorisation, layout, persistence, junction semantics) plus a gated private acceptance check; layering and release allowlist extended.
- Private references: PEW splice profile and acceptance results ship under git-ignored `references/private/`.

# 0.9.6 (2026-11-12)

- Added persisted deletion-review gate for unreferenced managed storage objects: pending by default; independent authorized reviewer and rationale; exact identity/inventory generation binding; freshness, expiry, references, holds, active leases and retention clearance checks; versioned decision history via aggregate repositories.
- Explicit fail-closed inventory/authorization ports, no permissive defaults. Read-only approval validation is not an executable deletion token. No S3 DELETE, garbage collector, registry fencing or production identity integration ships in this release.
- Added memory and DuckDB stand-in tests and generated review contract documentation. DataMesh does not assume AWS SQS or Fabric-specific workflow/notification behavior.

# 0.9.5 (2026-11-12)

- Fixed XLSX explicit-outline parent graph edges: asserted source hierarchy emits child_of; inferred indentation/name-code parents remain proposed_child_of. XLSX adapter provenance version advances 2 -> 3.
- Added permanent synthetic regression checking outline fields/graph agreement and protecting inferred-parent proposal semantics.
- Reran actual private PEW acceptance including controlled outline variants, SQL stand-in persistence, replay/current revisions and outgoing test-broker events. Results/evidence included in git-ignored private references. No live broker/database compatibility claim.
- Existing persisted records/inbox markers are not automatically rewritten; documented controlled handler-generation replay for rebuilding affected source occurrences.

# 0.9.4 (2026-11-12)

- Local Docker Compose stack: PostgreSQL 18, authenticated NATS 2.11 JetStream, one-shot migrations/stream bootstrap, nonroot durable worker, shared blob volume and explicit publisher/smoke tools. Loopback-only host ports; persistent named volumes; correct PostgreSQL 18 data mount.
- Generated git-ignored local credentials and pseudonym salt, retained across reruns; explicit image COPY allowlist excludes private references/secrets. Private profile read-only mount is opt-in by environment setting; no directory auto-ingestion.
- `scripts/local_stack.py`: init/config/up/smoke/status/logs/down; down retains all volumes. End-to-end smoke requires both committed object and confirmed stored event. CI compose-smoke job repeats after container restarts. Static tests executed locally; actual Docker deployment unexecuted here.
- Stock Postgres image: pgvector not installed by this stack. No production HA, TLS/subject ACLs, backups or immutable image-digest proof implied.

# 0.9.3 (2026-11-12)

- **Durable broker adapter architecture**: separate async `DurableBrokerPort`, `PublishReceipt`, `DurableConsumerSpec`, `DurableDelivery`; synchronous simulation API retained unchanged. Design: `docs/architecture/JETSTREAM.md`.
- NATS JetStream infrastructure adapter (optional `nats` extra), lazy connection, explicit stream provisioning, file-backed Limits retention with DiscardNew, independent RAW/EVENTS/TELEMETRY/QUARANTINE capacities, confirmed publishing with event-id dedup header, bounded durable pull consumers, explicit ack/retry/progress and durable replay start.
- Reversible per-level hex encoding preserves slash topics and dotted source IDs; final # maps to parent + descendant filters.
- Transactional worker: persistent per-handler inbox deduplication, commit-before-ack, lease heartbeats, rollback and delayed retry, transactional quarantine before terminal acknowledgment. Async outbox relay marks only confirmed publications. No end-to-end exactly-once promise.
- Durable ingestion composition routes existing source adapters (including the 0.9.1 PEW profile) into PostgreSQL repositories and outbox, not an ephemeral ring. Shared-volume content-addressed blob adapter; `raw_item_event` reused by both intake paths. Runnable `scripts/jetstream_service.py` supports administrative provisioning, file-intake publication and worker mode.
- Deterministic durable test double, adapter unit tests and optional live NATS integration test. Dedicated GitHub `jetstream` job. No server executed in the sandbox; cluster failover/security/load and combined PostgreSQL+NATS fault injection remain acceptance work.
- Private reference bundle retained; new broker decision trace ships under git-ignored `references/private/`.

# 0.9.2 (2026-11-12)

- Ubuntu deployment addendum: `scripts/deploy_postgres_ubuntu.sh` provisions dedicated localhost-only PostgreSQL 18 service, PGDG key fingerprint check, SCRAM login, root-only credentials, safe reruns and optional pgvector. Bash-only checks pass; actual APT/systemd deployment remains unexecuted.

- **Persistence layer** (repository pattern), design source `docs/architecture/PERSISTENCE.md`.
  - `app.application.persistence`: Pydantic contracts (`StoreResult`, `EdgeRecord`, `VersionedRecord`, `CommandRecord`, `StockPosition`, `Reservation`, `EmbeddingSpace`, `EmbeddingRecord`, `OutboxEntry`), `Protocol` repository ports, `UnitOfWork`, and use cases `persist_objects`, `save_aggregate` / `load_aggregate`, `run_once`, `reserve_stock`, `relay_outbox`, `documents_for`, `tasks_of`. No drivers, SQL or `json`; never imported by `app.domain`.
  - `app.infrastructure.persistence`: PostgreSQL 18 dialect, ordered idempotent migrations (001-005, opt-in 101 pgvector), SQL repositories with bound parameters only, `SqlUnitOfWork` (explicit READ COMMITTED transactions), in-memory repositories with snapshot rollback, and wiring (`build_postgres`, lazy psycopg 3; `build_duckdb_standin`; `build_memory`).
  - Source occurrences version by digest (same digest = no-op); edges are stored per source version and read through the current head; recursive traversal depth 1-6. Aggregates use compare-and-swap with full history. Commands apply at most once. Reservations use one conditional update plus `CHECK (reserved <= on_hand)` so competing claims cannot overcommit. Embeddings keep masks and model identity; sparse indices convert zero-based to one-based only in `vectors.py`. Outbox events (`domain.stored`) commit with the change and relay at least once.
  - Project documents from 0.9.1 persist unchanged: `tasks_of` returns tasks of the document's current revision by default.
- Shared contract suite `tests/test_persistence.py` runs on memory and a DuckDB stand-in; `PostgresContract` runs only with `DATAMESH_PG_DSN` and psycopg 3. New CI job `postgres-18` (service container) is the only evidence of PostgreSQL compatibility; it has not run for this release yet.
- Generated `docs/contracts/PERSISTENCE_SCHEMA.md` (`scripts/gen_persistence_docs.py --check` in CI); persistence slice added to the agency contract docs. Optional extra `postgres`.
- Messaging: event kind `domain.stored`, topic `stored/<kind>/<object_id>`.
- Private references: `/references/private/` is git-ignored explicitly; `scripts/export_public.py --with-private` builds a coordinator bundle that includes it, listed separately in the manifest, and refuses if Git would track any of it.

# 0.9.1 (2026-11-12)

- **Project estimation workbooks** (`xlsx` source format), design source `docs/pipelines/XLSX_WORKBOOK.md`.
  - Stdlib SpreadsheetML reader: raw cell text, formulas and cached values kept apart; shared formulas expanded by reference shifting; bold, italic, indent and Excel outline levels read for hierarchy evidence. No macro execution, external-link resolution or URL fetching.
  - `WorkbookProfile` contracts (anchors, vocabularies, catalogs, role matrix with `HierarchySpec` and `RoleClassRule`, line tables, reference and crosswalk checks). Unknown layouts are quarantined.
  - **Document tied to the project:** `IntakeBinding` on `RawItem` names the project or opportunity (governed external reference, supplied at intake, never parsed). A profile with `document_type` emits a `project_document` with a stable source-document identity, `document_of` its `project_reference`, and one `workbook_revision` per content hash. Unbound documents are kept and flagged.
  - **Task extraction:** phases (root), stems and sub-system headings, leaves under a sub-system (indent or name code, parent proposed). `wbs_code` / `parent_wbs_code` / `wbs_level` give an explicit hierarchy column per revision; `wbs_outline()` projects it for review. Sub-system codes resolve only against the index; template placeholders keep their example code unresolved.
  - Task x role demand only where inputs exist: blank never becomes zero, partial and explicit-zero states kept, labor hours = count x hours each with elapsed estimate = hours each, stale caches reported. Role codes split into series/number/year; labor source internal, contract or vendor (vendor hours flagged as priced elsewhere). Responsibility conflicts resolved by declared precedence with raw values kept.
  - BOM lines with one part-number claim each (unmapped, never collapsed), the line's own classification (group headers are context, never carried down), sub-system candidates, raw money text and external UOM authority.
  - Diagnostics, never repairs: inconsistent formula references, role-code mismatch, references beyond a sheet's used range, dependencies on excluded sheets, code crosswalk conflicts, formatting/text disagreement, unknown responsibility values.
- `docs/domain/DOMAIN_DEPENDENCY_GRAPH.md`: proposed implementation order for the 94 scaffolds (14 levels, 3 loops to cut, D01-D09 redlines applied).

# 0.9.0 (2026-11-12)

- **Domain entity scaffold** (`app.domain`), design source `docs/domain/DOMAIN_SCAFFOLD.md`. 94 classes: 82 names from a source class model plus 12 additions (ProductDefinition, AssetInstance, four Vendor subtypes, Shipment, CalendarBooking, BOM, BOMLine, RFI, Agent). Each has two fields (optional UUID, fixed `unreviewed-scaffold` status), rejects extra fields and fails closed on `require_accepted_definition()`. No business fields, permissions, lifecycles or inheritance between scaffolds.
- Generated reference `docs/contracts/DOMAIN_SCAFFOLD.md`, CI-gated by `scripts/gen_domain_scaffold_docs.py --check`.
- Release check allowlists `src/app/domain/`. Enterprise-specific records stay out of the public tree.
- Docs: removed an enterprise term from the ingestion page and an internal work-item title from the CNN/GNN pipeline page (both present in 0.8.0).

# 0.8.0 (2026-11-12)

- **Ingestion** (`app.application.ingest`, `app.infrastructure.ingest`), design source `docs/architecture/INGESTION.md`. External data reaches tensors in five explicit transforms: raw topic, adapter, domain object, IngestRing, tensor plan.
- **Hierarchical raw topics** `raw/<platform>/<format>/<source_id>`: subscribe by platform (`raw/sharepoint/#`), by format (`raw/+/pdf/#`) or both. Raw bytes stay in a blob store; envelopes carry key, SHA-256, size and media type only.
- **Adapters** (anti-corruption layer, deterministic): email (stdlib, reply links from `In-Reply-To`), docx (zip + XML, size-guarded), pdf (optional `pdf` extra, pypdf), json via declared `JsonMapping`, data contracts via a registry (`ProcessExecution` becomes a `process_execution` object whose incidence becomes typed relations), plain text. People become salted pseudonymous `ResourceRef` tokens (`res-<16 hex>`); objects stay things.
- **Quarantine**: malformed input becomes a `Rejection` on `quarantine/...`, never a partial object.
- **IngestRing** (not the simulator's BufferRing): bounded, per-consumer cursors, at-least-once redelivery, kind-aware trimming, `RingFull` backpressure turned into ordered deferral with `retry_deferred()`, idempotent versions (digest excludes intake time), exact lag gauge.
- **Tensorizer**: signed blake2b feature hashing (`words-v1+blake2b-signed-hash-v1`), numeric columns with presence masks, typed `edge_index`/`edge_type` (COO, batch-local), `FrozenProjection` (PCA to 3D fit once, discarded variance reported, deterministic sign, digest). Every `TensorBatch` carries lineage back to raw content SHA-256.
- Consumer map in the design page: GNN and ensemble read the ring; enrichment and probe read projected positions; CNN reads simulated fields, not the ring; three-body object-mass load stays blocked on an approved B2 mapping.
- Messaging: event kinds `raw.item`, `domain.object`, `ingest.rejection`; topics table updated.

# 0.7.0 (2026-11-12)

- **Probe** (`app.application.probe`, `app.infrastructure.probe`), backend only. A 2D plate inside the 3D fluid (frozen projection), re-aimed by aperture tilt and yaw (precession about the normal), offset, and spun by its phase; a slab takes in records in plate coordinates.
- Readings with independent masks: vortex (ring circulation, eta_kin, radial leakage, velocity winding certified under the analytic arc bound), field (vorticity, strain, speed), plane (planarity, unsigned tilt; no PCA handedness), states (slab, aperture, strengths, condensed, labelled, density ratio), spin gauges (global, local, balance of explicit strengths).
- **Barrier Lyapunov brackets** for plate offset and aperture radius: V = 0.5 ln(kb^2/(kb^2 - e^2)) gauge, outward moves follow the exact solution e = kb tanh(atanh(e0/kb) + v t/kb), inward pass unscaled, optional centring gain by splitting. The window is never left; cost does not grow with push size.
- **Lens** (hover and magnify words: hovered record tf-idf, lens contrast log-odds), **candidates** (mutual-kNN clusters in the aperture with suggested terms, plus enrichment shortcut pairs inside the aperture), **LabelBook** (validated human label events on records, clusters or pairs; blind flag; published as `hil.label`; conflicts reported).
- Analytic controls (rotation, shear, saddle, translation, dilation) reproduced exactly by the ring kernel. Point-vortex control documents that circulation and eta_kin are independent: irrotational strain outside the core.
- Messaging: new event kind `hil.label`.

# 0.6.0 (2026-11-12)

- **Embedding enrichment** (`app.application.enrichment`, `app.infrastructure.enrichment`): the Condensation Chamber v8 rules as a backend contract. A plate run's object body is the ionizing ray; a slab of the frozen embedding at the ray's height ionizes, supersaturates and condenses. Outputs a sparse code (4 arms x N x 12 orbit-phase bins), pass order classes, shortcut candidates (same phase, far in kNN) and small-world readouts, for four lockstep arms `{real, null} x {activation on, off}`.
- Two nulls: `axis_shuffle` (chamber parity) and new `height_preserving` (each record keeps its slab height, in-plane positions shuffled), with `shortcut_excess_on/off` reported against the chosen null.
- Small-world readout reports global efficiency, because path length can rise when shortcuts join disconnected components.
- Finding written into the design page: under these rules the sparse code is a deterministic function of the frozen coordinates, so shortcuts describe how the cloud folds against the normal. In the planted test both nulls match the real arm. Enrichment beyond geometry needs ion tracks from outside evidence (planned).

# 0.5.0 (2026-11-12)

Implementation layer for process-first agency dashboards. Docs-first: each slice has an Obsidian-compatible design page (Mermaid diagrams, runnable doctests) written before its code.

- **Process-first domain** (`app.application.process`): `ProcessType`, `ProcessExecution`, `ObjectIncidence`, `CapabilityBinding`, `AuthorityRef`, `ObjectEvent`. Objects are things, never people; resources appear only as executors. Gates are control executions. Release requires authority, verification evidence the gate actually read or checked, and computed status: simulated work never releases. `derive_object_events` gives births at `produces`, deaths at `consumes`, state changes otherwise, and rejects lifecycle violations. `ParticipationEdge` is now a derived projection.
- **Plate and spatial isosceles three-body** (`app.application.plate`, `app.infrastructure.plate`): two mirrored side bodies define a 2D plate with global spin; the object body rides the plate normal and crosses the plate. Velocity Verlet, inertial snapshots only, live object-mass events without resets, interpolated crossings, energy/spin/mirror diagnostics. Plate field of regularised local vortices with analytic Jacobians in plate and inertial frames. New analytic whole-arc derivative bound feeds the existing velocity-winding certificate.
- **Message broker** (`app.application.messaging`, `app.infrastructure.messaging`): content-hashed `EventEnvelope` (computed needs a real timestamp, simulated needs model time), MQTT-style topics, `MessageBrokerPort`, in-memory broker (append-only log, replay, FIFO, idempotent, dead letters). `HandoffRouter` turns plate crossings into at most one pending candidate per object and route; only a gate execution resolves it.
- New generated reference `docs/contracts/AGENCY_CONTRACTS.md` + 18 JSON schemas, CI-gated by `scripts/gen_agency_contract_docs.py --check`. Docs index and docs-first principles added.
- Export script reads the version from `src/app/_version.py`.

Not done: MQTT/IoT adapter (port only), vortex dynamics on the plate (vortices pinned), body-field coupling arm, multi-plate physics, embedding-to-plate mapping, any process catalogue or empirical validation. No new license decision.

# 0.4.0 (2026-11-11)

First curated GitHub-candidate distribution of the accumulated gauge/geodesic/winding toolkit. Prior exports had no declared package version; 0.4.0 is the new explicit release version, not a claim of prior published tags.

- Retained existing app.* application/simulation, application/gauge, infrastructure/tensors and infrastructure/gauge APIs.
- Added installable metadata, wheel/source distribution, public CI and an explicit public export allowlist.
- Default-denied reference data; only an empty public manifest and boundary README ship.
- Excluded enterprise application modules, source-derived frame fixtures, original datasets, internal navigation/context, old archive inventories and private provenance links.
- Added confidentiality/index checks and export tamper controls. Human classification, rights and license approval still required.
- Fixed empty shared-store replacement in simulation wiring (previously a falsey empty store was discarded).
- Retained research limitations; no business/process validation or new public license claimed.

Public-slice verification: 89 tests pass (82 retained generic/synthetic tests + 7 release/shared-store/kernel controls). Original enterprise/source-derived fixture suites are intentionally not shipped; this is not a claim that all 125 prior-repo tests are included. Wheel built and installed locally without fetching dependencies.
