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

## Composition

`app.infrastructure.ingest.reference_documents.ingest_and_hydrate` accepts an absolute private root, explicit relative source/output paths, a manifest-supplied opaque source/revision handle, a separately configured expected source SHA-256, a reviewed `ReferenceIngestProfile`, the application's existing `UnitOfWorkFactory`, and an aware recording time. It returns the private bundle and a receipt containing opaque graph handles only. A production caller must pass its already configured durable UoW; the in-memory UoW is for tests only.

Synthetic acceptance tests exercise extraction, nested boundaries, JSON verification, path containment, repeat-safe graph writes and the in-memory UoW. They do not ingest or publish real standards. Real-source acceptance still requires approved source files and a private runtime composition.
