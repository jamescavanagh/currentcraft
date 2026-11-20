# P4 source and destination adapter boundary

Status: **design specification, not implemented ports or live wiring**. Governing contracts and migration decisions: [P4 design contracts](../domain/P4_DESIGN_CONTRACTS.md). Execution and failure boundaries: [P4 integration](P4_INTEGRATION.md).

## Dependency direction

Private source adapter -> private PublicSourceSanitizer implementation -> public application DTOs/use cases -> public destination port -> configured destination adapter. Domain imports neither application nor infrastructure. Application depends on contracts and ports, never concrete adapters. Public HTTP composition uses the existing wiring module to inject configured implementations; no credentials, raw source keys, part crosswalks or actual project destination paths enter domain/application modules.

PublicSourceSanitizer is a named composition responsibility, **not an existing class or proof of sanitization**. Future ports belong in the application layer after contract review. This checkpoint creates no port implementation or private module.

## Source boundary and ownership

| Responsibility | Owner | Required behavior |
| --- | --- | --- |
| Authentication, ERP/OData requests, pagination and source capability detection | Private source adapter | Use private credentials/configuration. Preserve source meaning and raw evidence privately. Declare stable_snapshot/change_token/best_effort honestly. |
| Raw business keys and actual part-number resolution | Private adapter/sanitizer using private server-readable references | Resolve to stable opaque public UUIDs with private reversible crosswalk if required. Never hash/display a real part number as a public label or assume hashing removes sensitivity. |
| Raw-to-public field and metadata selection | PublicSourceSanitizer implementation at private/public boundary | Construct PublicSourceRecord from an allowlist, reject unexpected fields, validate safe classifications and exact Decimal/time semantics. Do not pass arbitrary source descriptions through string metadata. |
| Public invariant enforcement | Application DTOs and use cases | Revalidate before persistence and outward surfaces; reject unknown fields, incompatible measures and inconsistent provenance. Type validation alone is not a secret detector. |
| Production mappings/classification/effective dates | Named private configuration owner, not assigned here | Supply versioned rules and evidence. Missing configuration blocks live composition; synthetic defaults cannot stand in for approved mappings. |

Raw payloads do not enter public repositories, checkpoints, exceptions, logs, traces, fixtures, generated docs, HTTP responses, graph labels, exports or outbox events. Private extraction storage is a separate controlled concern, not the public source-object repository. Evidence IDs exposed publicly are opaque references; fetching private evidence requires separate authorized resolution.

### Existing envelope and explicit gaps

PublicSourceRecord currently allows only source_id, optional project_id, evidence_id, category, optional exact amount/currency/unit, occurred_at, original_date and date_precision. It has no raw part number, source key or free-text description field. It also has **no source-version field**: review a versioned provenance envelope or immutable manifest association before claiming live source-version traceability. Do not add a required field to the accepted DTO silently.

ExtractionManifest carries extraction/profile/contract IDs, consistency capability/token, page completeness, digest, window, receipt time and limitation. Those string fields are not automatically safe: source tokens must be opaque public handles to private token state; limitations must be controlled safe codes/text, not upstream exception payloads. Profile IDs and validation errors need the same treatment. A real source token, URL, account identifier or part description must not be smuggled into an allowlisted string field.

Known source date without time retains original_date and gets exactly 09:00 America/Los_Angeles with seasonal offset and assigned precision. Unknown stays unknown; observed timestamps are unchanged. This synthetic convention neither changes accounting date meaning nor grants production calendar policy.

## Proposed public source-port capabilities

After contract review, define array-free protocols for extraction of sanitized records plus immutable manifest and for checking resumability using opaque handles. The public contract must expose:

- Explicit source/profile/contract versions, reporting window/cutoff, extraction identity and complete population/coverage semantics.
- Exact sanitized record bytes or a public-safe content-addressed reference; record/version evidence linkage; digest over the defined canonical public payload.
- Snapshot/change-token capability or explicit best-effort limitation, page count/completeness and receipt time.
- Structured safe failure categories, including incomplete extraction, consistency violation, capability change, missing private mapping and transient transport failure. No raw upstream exception text.

Do not claim stable snapshots for best-effort paginated sources. Never stitch pages across fetches. Changed token means full refetch/recompute; changed profile/window/capability or incomplete extraction blocks reuse. A partial extract's missing row is not deletion. The future adapter conformance suite must cover each branch of resume_action plus full checkpoint validation.

## Destination boundary

The application names an opaque destination/profile, exact immutable product/output reference and digest, and stable delivery identity. The private configured adapter resolves actual ClickUp location, operation, permissions and credentials. Public code must never invent a live location or silently switch create/update behavior.

A future destination port must support:

1. Delivery intent identity and a reconcile/status query **before** retrying an uncertain external operation.
2. Delivery of the exact validated payload/version with a stable idempotency/correlation key, where supported.
3. Destination verification returning attempt, product version, opaque destination, public-safe document ID and timezone-aware verified receipt time.
4. Explicit rejected, pending/unknown and verified outcomes, with safe errors and disclosed limitations.

DeliveryAcknowledgment is a verified application receipt, not a queue acknowledgment. A returned task/job ID alone is insufficient unless configured completion semantics verify the actual document/output. If a returned identifier is sensitive or outside the existing document_id pattern, define an explicit safe-handle resolver; do not weaken the DTO or leak URLs. Only the configured set of required outputs determines completion; one receipt cannot stand for several destinations. Pin destination configuration/version and required output identities in the prepared checkpoint.

No exactly-once external-write guarantee is assumed. If the real destination cannot reconcile delivery identity after timeout, automatic retry/create is unsafe and must block for investigation. Private source/destination adapters may have different capabilities; test both against the same public synthetic conformance cases without publishing real payloads.

## Private wiring and public egress

- Keep credentials, mappings, part-number crosswalks, actual ERP schemas and live destination configuration outside public packaging. Synthetic profiles use opaque IDs only.
- Existing HTTP wiring is the composition entry point; application handlers receive interfaces/configuration, not private modules or environment lookups.
- Live readiness requires explicit source capability, safe labels/mapping versions, destination semantics, reporting policy and authorization. An unconfigured live request fails closed; it never falls back to a synthetic adapter.
- Before storage, event emission, graph/API/export delivery and diagnostics, apply outward allowlist validation. Log only opaque IDs and controlled error codes, not rejected values or framework ValidationError dumps that may contain input.
- Release/package checks and synthetic sentinels must cover each outward surface when implemented, including generated schemas/examples and build artifacts. Existing ingress tests establish only their tested DTO boundary, not end-to-end leak prevention.

## Acceptance before implementation

Review the source-version/provenance envelope, opaque token/receipt handles, destination identity and required-output rules. Then implement synthetic conformance fixtures for pagination changes, missing mappings, unsafe metadata, timed-out writes, exact receipt matching and unavailable reconciliation. No private integration is implemented or approved by this document.
