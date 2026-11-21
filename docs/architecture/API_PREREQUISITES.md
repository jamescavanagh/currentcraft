---
title: Document API application prerequisites
version: 0.10.0
status: implemented prerequisite slice; HTTP document routes remain pending
tags: [architecture, ingestion, messaging, http]
---

# Document API application prerequisites

Addendum to HTTP_DOCUMENTS.md: this completes its three remaining application
prerequisites, not the HTTP routes, DTOs, retry storage, OpenAPI or Compose API
integration. The limits and privacy boundary in that design still apply.

## Stable identities

The XLSX adapter calls the shared application document_id and
subject_reference_id helpers. Existing document, subject, revision, task and
relation identities and serialized projections remain byte-identical. Synthetic
fixture tests compare all serialized objects against the old inline formulas,
with and without binding and with changed workbook bytes. Identity inputs remain
explicit; no identity is inferred from filenames or cells.

## Transactional handler outcomes

A durable handler returns "applied", "rejected", or None (legacy success).
DurableIngestHandler returns "rejected" after staging an adapter rejection event,
and "applied" after staging extracted objects. TransactionalWorker commits the
handler's outcome in the same UoW as its writes/outbox before ack. It does not
create a second quarantine event for a handler-reported rejection. Unexpected
return values raise a safe error and roll back into the existing retry policy.

Invalid envelopes and exhausted retries retain their existing terminal rejection
path. Ack failure permits replay; the unchanged inbox_key marker prevents
repeating extraction or quarantine publication. A failed commit cannot be acked.
intake_status reads that same marker: absent is pending, applied is processed,
rejected is quarantined. Neither queued nor processed establishes work approval.
Historical applied markers may hide adapter rejections; they are not rewritten.
This fixes new worker records, not historical ambiguity or HTTP acceptance.

## Token connection reuse

Local runtime calls connect_jetstream instead of maintaining private connection
code. Preserve the existing 60-attempt startup loop, 1-second backoff,
2-second connect timeout and two reconnect attempts. The helper accepts optional
connect_timeout and max_reconnect_attempts overrides; omitted timeout is not
forwarded, and default reconnect attempts remain 10. Token/credentials conflict
protection and TLS behavior remain unchanged. Secrets are read from files and
never logged. No stream provisioning occurs in the connection helper.

## Acceptance

Test whole-fixture serialization equality; successful and rejected adapter
status; commit-before-ack, lost-ack replay, commit failure rollback, malformed
input and unknown adapter; legacy None handlers; invalid handler outcomes;
connection defaults/overrides and runtime's bounded startup failure behavior.
Run existing query, identity, workbook, durable messaging, local-stack and
layering tests. Run release and generated-doc checks, and report missing
optional dependencies and unrun PostgreSQL/NATS/Docker gates explicitly.
