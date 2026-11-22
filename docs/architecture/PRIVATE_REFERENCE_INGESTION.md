---
title: Private reference-document ingestion
version: currentcraft-ref-document/v1
status: implementation candidate; source-specific acceptance pending
---

# Private reference-document ingestion

This path turns an explicitly selected private source document into an exact-text JSON snapshot, then hydrates source-literal nodes through the existing object/graph unit of work:

```text
pinned source bytes + private extraction profile
  -> read-only PDF or UTF-8 extraction
  -> document / candidate section / passage tree
  -> hash-pinned JSON under references/private/
  -> independent JSON and payload verification
  -> atomic source-object and typed-edge persistence
```

## Fractal structure, not interpretation

The root represents the source document. A private, reviewed profile may identify headings with a trusted regular expression; numbered headings form nested sections, and bounded passages retain exact offsets into the extracted page text. Unrecognized lines remain passages. There is no standards-specific vocabulary, crosswalk, rule execution, semantic mapping or automatic clause interpretation in public code. A section boundary is a parser candidate, not evidence that the source is complete, authoritative, current, applicable or approved.

The private JSON preserves extracted page text, source-relative name, source and profile digests, extractor version, node order, parent handles and Unicode-codepoint spans. The source/revision handle comes from an explicit private REF manifest; IDs are never inferred from filenames or content hashes. Graph objects preserve those spans and source hashes; each child has a typed `part_of` edge. All six-type/canonical business records remain unchanged. The graph entries are labeled `source_literal_candidate` and create no decision authority.

## Privacy and integrity boundary

- Configure the root as the local `references/private/` directory. The loader rejects any other root name, absolute or parent-traversing paths, symlinks, unsupported formats, oversize inputs and unpinned source bytes.
- Output is atomically written as a mode-0600 JSON file inside that same root. The private bundle is never placed in `references/public/`; source text and derived JSON are not fixtures, package data or public artifacts.
- Re-loading JSON requires its expected byte digest as a separate trusted input, rejects duplicate keys, verifies the closed model and canonical payload digest, then issues an independent selection receipt. A receipt embedded in JSON is not proof of verification.
- Hydration writes every object plus an idempotency record in one existing unit-of-work transaction. No filesystem path, source bytes, private labels or mappings are published to a broker or external service.
- The code does not enforce source rights, classification, retention or operating-system access control. The caller must authorize source use and protect the private volume. Hash checks prove byte identity, not trustworthiness.

## Supported extraction and limits

PDF text extraction uses the optional `pypdf` extra in strict, read-only mode; encrypted PDFs are rejected. UTF-8 text and Markdown are supported by the standard library. Scanned-PDF OCR, external links, macros, network retrieval and automatic source discovery are not supported. The exact extracted text, not binary layout, is the unit referenced by offsets.

## Six acceptance corrections

1. New REF parent relations pin `target_version`, stored as `dst_version` beside
   `src_version` by migration 006. Parents are written before children; the actual
   returned parent version is pinned. Legacy unpinned edges stay null, not guessed.
   Current traversal is not a historical snapshot traversal.
2. Current REF descendant listings, related reads, edges and traversals require their
   payload digest to match their manifest handle's current root payload, identically
   in memory and SQL. Direct lookup and history remain available. Nothing is deleted.
   Earlier command replay cannot restore old heads; failed transactions roll back.
3. The loader issues an identity-bound, weakly held process-local capability.
   Hydration checks it as well as receipt/bundle consistency. Hand-built, copied and
   JSON-round-tripped receipts cannot mint capabilities. Reload pinned files after a
   process restart. This protects against caller data, not hostile Python code in the
   same process; it is neither a digital signature nor a permission grant.
4. Profiles declare `coverage` as full, partial or unknown. Partial requires a private
   reason. Both coverage and reason propagate into JSON and every graph node. Preview
   status must be declared at intake; no filename or parser success establishes full
   coverage. Unspecified coverage stays unknown. Metadata changes bundle/profile
   digests, not source handles or node identities; the determinism golden changes.
5. `.owl` and `.rdf` accept exact UTF-8 RDF/XML source capture with a validated RDF
   root. DTD/entity declarations are rejected before parsing; nothing dereferences
   imports or external resources. Markup is retained as bounded source-literal
   passages, not interpreted as semantic triples, class hierarchies or ownership.
   Reasoning, Turtle and OWL Functional Syntax are not implemented.
6. Full private locators up to 1,024 characters remain in `source_name`. Locators over
   500 characters use the neutral root title `Reference document` without truncating
   the locator.

All six former expected failures are required passing regressions. Store-specific
checks run against memory, DuckDB and the gated PostgreSQL acceptance class.
Synthetic correctness does not establish real-standard completeness or authority.

## Composition

`app.infrastructure.ingest.reference_documents.ingest_and_hydrate` accepts an absolute private root, explicit relative source/output paths, a manifest-supplied opaque source/revision handle, a separately configured expected source SHA-256, a reviewed `ReferenceIngestProfile`, the application's existing `UnitOfWorkFactory`, and an aware recording time. It returns the private bundle and a receipt containing opaque graph handles only. A production caller must pass its already configured durable UoW; the in-memory UoW is for tests only.

Synthetic acceptance tests exercise extraction, nested boundaries, JSON verification, path containment, repeat-safe graph writes and the in-memory UoW. They do not ingest or publish real standards. Real-source acceptance still requires approved source files and a private runtime composition.
