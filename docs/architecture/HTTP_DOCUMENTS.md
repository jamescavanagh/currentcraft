---
title: HTTP document API
version: 0.10.0
status: design and application queries implemented; document HTTP routes not implemented
tags: [currentcraft, architecture, http, ingestion]
---

# HTTP document API

This extends the HTTP shell and the shared identity decision. The API runs
beside the worker: store bytes -> confirmed JetStream publish -> worker ->
PostgreSQL. Only the worker extracts documents and writes source objects.
The API never parses workbooks, migrates schemas or provisions streams.

## Identity, access and authority

Use platform="file" and the same explicit stable source_id as the CLI.
Preserve existing document/subject identities. Never infer source identity
from filenames or workbook cells. A local bearer token proves possession,
not personal identity, roles or approval authority. Read secrets from files,
compare tokens in constant time and fail closed when configuration is absent.
All /v1 endpoints require the token. Bind the local service to localhost.

Exclude deletion review, deletes, OIDC, public CORS, ClickUp import, S3,
simulation and HFGT endpoints. Queued is not extracted. Extracted tasks are
source occurrences, not approved or executable work.

## Intended endpoints

Document HTTP routes are specified, not implemented by this slice:

* POST /v1/intake/documents: multipart intake, confirmed publish, then 202.
* GET /v1/intake/{event_id}: pending, processed or quarantined.
* GET /v1/documents/{document_id}: current project-document head.
* GET /v1/documents/{document_id}/tasks?all_revisions=false: current tasks,
  or all retained revisions when explicitly requested.
* GET /v1/documents/{document_id}/wbs?format=json|csv: selected current
  revision's phase/task outline.
* GET /v1/subjects/{subject_kind}/{namespace}/{reference}/documents:
  documents for an explicit subject reference.

The existing shell implements /healthz, /readyz and /v1/auth/check.
Liveness touches no dependencies; readiness returns safe 503 on failure.
Only HTTP wiring imports infrastructure. Synchronous storage calls run in a
threadpool; application queries import no frameworks or drivers.

## Intake and lifecycle

Required fields: file, format (xlsx or text), source_id; mapping for XLSX.
Optional binding uses subject_kind, subject_namespace, subject_ref,
document_type and revision_label. Any binding field requires all four core
fields. Validate existing RawItem/IntakeBinding contracts before blob writes.
Profile contents and mappings remain private.

Enforce at most 64 MiB of file bytes while reading. Do not trust
Content-Length. Bound multipart overhead, field/file counts and spooling;
authenticate before consuming uploads. Always close handles. Return 413
for size, 422 for invalid format/identity/binding, and safe 503 for failed
blob writes or publish. Never return 202 without confirmed durable publish.

For identical source/content/format/mapping/complete binding, atomically
persist and reuse the real first validated receipt and timestamp before
publishing. Concurrent requests select one first receipt. Every retry still
publishes and waits for confirmation, including after an earlier failure.
Never invent timestamps, weaken event hashes or change CLI construction.

Identical submissions are retries, not restoration of an older document head.
An explicitly changed revision_label creates a distinct submission for
deliberate reprocessing. Restoration is a future explicit action, not an
implicit side effect. Broker-window deduplication is not exactly-once.
Failed publishing may leave an unreferenced blob; introduce no auto-deletion.

202 means "durably queued; not extracted". Receipt fields must pass the same
privacy boundary as read DTOs. Do not echo raw source IDs simply because an
older handoff listed them. Expose opaque event/status handles.

## Privacy boundary

Enterprise data, reference dictionaries, mappings and packages stay private
server-side. Public artifacts, UI and API use opaque identities, never actual
part numbers. A bearer token or trusted operator is not an exception.
Internal application queries return governed source objects, NOT response
DTOs. Never directly serialize them into HTTP.

Before adding routes, implement a tested allowlist projection with opaque
external handles. Exclude raw titles, arbitrary fields, relation evidence,
provenance, source references, mapping names and blob paths by default.
Hashing object_id alone does not redact everything else. Do not guess whether
free text contains identifiers; withhold it unless a governed projection
explicitly permits a safe value.

Apply the rule to JSON, CSV, error payloads, URLs and logs. WBS CSV keeps
OUTLINE_COLUMNS but withholds/substitutes private cells and escapes formula
prefixes. Internal query/WBS output is not automatically safe for disclosure.
Use synthetic public fixtures only.

## Committed-state queries

document_head returns a project document or None. Unknown IDs and other
object kinds produce None for later safe 404 translation.
document_tasks selects the head and current revision within one unit of
work. Current-only reads select tasks from that revision only.
All-revisions reads retain the extracted_from document boundary.
document_outline selects phase_scope/wbs_task objects for the chosen
revision. No current revision yields an empty result. Multiple current
revisions are an integrity error, not permission to combine their outlines.
Queries never commit.

One unit of work does not establish PostgreSQL repeatable-read isolation.
These functions pin a chosen revision identity, not a stronger cross-request
or cross-statement snapshot guarantee. Immutability/concurrent-worker
behavior requires live database acceptance.

intake_status uses the exact public inbox_key used by the worker. No marker
means pending, including unknown IDs; it does not prove queue membership.
Applied means processed source occurrences; rejected means quarantined.
The legacy adapter can emit a rejection while returning None, which the
generic worker records as applied. This slice reflects stored outcomes,
does not repair historical ambiguity and does not claim HTTP quarantine
acceptance. Follow-up must commit adapter rejection and inbox outcome
consistently before exposing status as end-to-end extraction truth.

Subject lookup uses the validated existing identity helper and document_of
relation. Invalid subject grammar raises the existing contract validation
error for later safe HTTP translation.

## Acceptance and limits

Test memory/DuckDB query contracts, workbook output, unknown/wrong kinds,
revision selection, malformed multiple heads, subject validation, no query
commits, legacy/public inbox-key equality and actual worker markers.
Stand-ins do not establish PostgreSQL/NATS/Docker compatibility.

Remaining prerequisites: wire shared helpers into XLSX with byte-identical
regressions, integrate worker quarantine outcomes, and reuse the existing
token connection helper in runtime. HTTP routes, safe response projections,
retry receipt storage, generated OpenAPI changes and Compose/API smoke remain
follow-up work. Do not weaken layering or release checks.

Generate OpenAPI via scripts/gen_openapi.py, never hand-edit JSON.
CI must require API tests, not silently skip dependencies. Run real database,
JetStream and Compose/API smoke on the eventual exact PR commit and report
those separately from local stand-ins. No merge, deployment, version bump,
release tag or production-readiness claim is implied by this slice.
