---
title: Shared HTTP and CLI document identity
version: 0.10.0
status: decision recorded; helpers added; endpoint integration pending
tags: [currentcraft, architecture, http, ingestion]
---

# Shared source identity

The coordinator selected shared API/CLI document identity on November 21, 2026.
HTTP intake must use `platform="file"`, matching the existing publisher CLI,
and the same explicit stable `source_id`. Neither filenames nor workbook cells
establish source identity. Existing document, subject-reference and revision
identities must remain unchanged.

Application helpers in `ingest.identity` preserve the existing SHA-256 formulas.
The compatibility tests compare these helpers with the current XLSX adapter.
This groundwork does not yet change the adapter or implement document endpoints.

A shared local bearer token authenticates possession only, not personal identity
or approval authority. Keep deletion, OIDC, simulation and HFGT endpoints out of
the document implementation. Queue confirmation is not extraction; extracted
tasks are source occurrences, not approved work.

## Retry consideration for the endpoint implementation

Existing raw event ids include the actual intake timestamp. Repeated uploads
therefore need durable first-receipt reuse if the API is to return the same event
and a broker duplicate receipt. Do not invent a fixed timestamp, weaken envelope
hash validation, or change existing CLI identities to obtain deduplication.
That storage and endpoint integration are not included in this groundwork PR.
