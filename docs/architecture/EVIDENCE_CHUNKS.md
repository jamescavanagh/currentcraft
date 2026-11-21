---
title: Hierarchical evidence chunks
version: currentcraft-evidence/v1
status: contracts implemented; extraction and persistence not implemented
tags: [currentcraft, evidence, contracts, provenance]
---

# Hierarchical evidence chunks

## Purpose and scope

Pure application values describe page, sheet, BOM row, email and chat-thread
evidence without copying source content. Every chunk references explicit opaque
file, revision and project identities. Revision identity comes from the document
lifecycle lane, not from filename parsing or new identity logic here.

Done when all five kinds, hierarchy and provenance validate on synthetic data,
every field has a description, schemas/reference are generated and drift-checked,
and handles pass unchanged to the evaluation harness. Records never grant approval.

## Entities and rules

- `EvidenceTextOffsets`: nonempty half-open `[start, end)` span, zero-based,
  measured in explicitly declared Unicode code points or bytes in the exact
  extractor output identified by provenance. End must exceed start.
- `EvidenceCellRange`: opaque worksheet handle and one-based inclusive row and
  column bounds. Last bounds must not precede first bounds.
- `EvidenceProvenance`: opaque source locator, extractor name/version and SHA-256
  of its configuration. Page numbers are one-based. Offsets and cell ranges are
  mutually exclusive. Paths, URLs, addresses, text and original source identifiers
  resolve privately server-side; they are not fields on this contract. Offsets
  reference declared extractor output, not guessed positions in a source binary.
  Changed output/configuration requires new handles from the future identity owner.
- `EvidenceChunk`: schema version, opaque chunk handle, kind, file/revision/project
  references, optional parent handle and required provenance. Handles use ASCII
  letters, digits, underscores and hyphens, 1 to 200 characters. Syntax cannot
  prove privacy or authorization. Self-parenting is forbidden.
- `EvidenceChunkSet`: closed snapshot. Handles are unique. Every parent occurs
  in the set and shares the child's explicit file, revision and project binding.
  Only sheet -> BOM row containment is allowed in v1; all other kinds are roots.
  BOM rows require a sheet parent, matching worksheet handle and cell range
  contained in the parent range. Email and chat thread are separate root kinds,
  not a claim that an email is a chat message. Empty snapshots prove no absence.

All integer positions are strict: booleans, strings and floats are rejected.

- Page: page number required, optional offsets, no cell range.
- Sheet: cell range required, no page number or offsets.
- BOM row: single-row cell range required, no page number or offsets.
- Email: offsets required, no page number or cell range.
- Chat thread: offsets required, no page number or cell range.

These shallow edge rules exclude cycles by construction. Ordering is not identity.
No identifiers are generated, normalized or changed. Different files can coexist
but cannot be joined by containment. This is not a partial subtree or paginated
response. Alternate hierarchy shapes and cross-file relations need a later version.

## Evaluation boundary

`EvidenceChunk.chunk_id` passes unchanged to `RelevanceJudgment.item_id` and
`RankedRun.items`. Evaluation receives handles, not locators or content. Unjudged
items stay unknown. A relevance grade is not authority.

## Acceptance tests

Synthetic tests cover all five kinds, Python/JSON round trips, frozen/closed
models, descriptions, schema registration, strict bounds, locator mismatches,
duplicate/missing/self/invalid parents, mixed bindings, BOM containment,
evaluation compatibility and unchanged identifiers. JSON Schema covers structural
rules; Pydantic adds cross-field and cross-record validation. Schema-only
validation is not equivalent to full hierarchy validation.

## Limits and sequencing

No extractor, adapter, storage, ingestion, HTTP, embeddings, vector search or
identity-generation policy. Existence, resolution, authorization, extractor
reproducibility and semantic correctness remain future checks. These contracts
cannot detect a dishonest source and are internal application values, not HTTP DTOs.

DWG remains opaque metadata/hash only. Content chunks reference the companion
PDF's own file and revision, not the DWG. No adapter/media-type enforcement exists
in this slice. Ingest integration waits for the 0.10.0 intake merge and rebase.
Domain document, HTTP, deploy and OpenAPI paths stay untouched. Package version
stays unchanged: this is an unreleased slice, not a release.
