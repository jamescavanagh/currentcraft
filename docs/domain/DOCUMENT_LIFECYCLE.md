---
title: Drawing representation and document lifecycle
version: 0.11.0-proposal
tags: [currentcraft, domain, document, decision-record]
---

# Drawing representation and document lifecycle

Status: **proposed decision record for review**, not accepted operating policy.
Target release: 0.11.0 (evidence baseline). This page is docs-first: no code
changes until the 0.10.0 document read endpoints merge, because those endpoints
serialize `Document` and would conflict with these contract changes.

It closes two rows of the decision-gap ledger in [V1_DOMAIN.md](V1_DOMAIN.md):
"Drawing as document" and "Readiness and document lifecycle" (the document half;
work-release readiness stays with the release policy).

## Context

What exists on `main` (0.9.9):

| Class | State | Relevant behavior |
| --- | --- | --- |
| `Document` | V1 proposal | Long-lived identity: project, name, source version, storage locator, source type label, source state. `transition()` raises `document lifecycle policy is not defined`. |
| `Revision` | V1 proposal | Immutable source-reported revision: label, artifact locator, content hash, `supersedes_id`. Separate from document identity; no inferred current revision. |
| `ReferenceDocument` | V1 proposal | Contextual reference to a document by `document_id`; not a duplicate artifact. |
| `Drawing`, `Submittal`, `Report` | unreviewed scaffolds | Two fields, fail-closed acceptance guard. |

Two precedents shape the decision. `Revision` and `ReferenceDocument` already
attach to a document by reference instead of inheriting from it. And the
[dependency graph](DOMAIN_DEPENDENCY_GRAPH.md) has already retired inheritance
assumptions elsewhere (Order does not inherit Document; Product splits into
ProductDefinition and AssetInstance).

Downstream releases need this settled: the 0.13.0 expectation grammar generates
expected document classes, and readiness (0.14.0) reports which expected
documents are present, superseded or missing.

## Decision 1: Drawing is a facet of Document, not a subclass

**Proposed:** keep `Document` as the only document identity. Add a
`document_class` fact resolved from a versioned reference dictionary. Re-define
`Drawing` (same import path) as a facet record that references a document, the
same pattern as `ReferenceDocument`.

```text
Document (identity, document_class = drawing_sheet)
  <- Drawing facet: document_id, sheet_number, discipline, title, set membership
  <- Revision: label, artifact, content hash, supersedes, lifecycle state
```

| Option | Verdict | Reason |
| --- | --- | --- |
| `Drawing(Document)` inheritance | rejected | Inherits document lifecycle and `kind` literal; conflates a sheet with a set; contradicts the composition precedents above. |
| `document_class` fact only | rejected as sufficient | Loses drawing-specific facts that drive matching: sheet number, discipline, set membership. |
| **Document identity + Drawing facet + class fact** | proposed | One identity model; drawing facts live where they are evidenced; other classes (submittal package, report) can add facets later without new identity types. |

### Sheets and sets

- A **drawing sheet** is a `Document` with class `drawing_sheet` and a `Drawing` facet.
- A **drawing set** is a `Document` with class `drawing_set`.
- Membership is revision-scoped: set revision R includes specific sheet revisions
  (`includes_revision`). A sheet can revise without the set revising, and the
  reverse. Set revision labels never imply sheet revision labels.
- Sheet numbers and disciplines are source facts (observed or inferred with a
  derivation), never parsed into identity.

### Submittal

A submittal is not a document class. It is an **issue event**: a package of
specific revisions sent for a stated purpose to a recipient, with a recorded
response. Proposed fields: project, issued revision IDs, issue purpose
(dictionary reference), recipient party, issue time, response code (dictionary
reference, unknown until evidenced) and response evidence. The submittal's own
transmittal document, when one exists, is an ordinary `Document`.

## Decision 2: Lifecycle state belongs to Revision, not Document

**Proposed:** `Document` stays stateless identity; its `transition()` keeps
failing closed and is deprecated. Each `Revision` carries a common-data-environment
state aligned with ISO 19650:

| State | Meaning | Is it approval? |
| --- | --- | --- |
| `wip` | Work in progress inside the producing team | No |
| `shared` | Released to other teams for coordination or review | No |
| `published` | Authorized for its stated issue purpose | Only with release evidence (below) |
| `archived` | Superseded, withdrawn or historical; retained, never deleted | No |

**Issue purpose is separate from state.** "For review", "for construction" and
"record / as-built" are purposes (dictionary references) carried on the
transition, not extra states. A revision can be published for one purpose and
not another.

### Captured state versus governed transition

This is the core rule. Two different things must never share a code path:

1. **Captured state** is a fact about the source: "this file sits in the
   published-set folder" or "the title block says issued for construction".
   It is a `Fact` with observed or inferred status and evidence IDs. Capture is
   allowed now.
2. **Governed transition** is a decision that a revision *is* published for a
   purpose. It is a `StateTransition` with actor, authority reference, evidence
   and target version, using the existing P4 contracts. Governed transitions keep
   failing closed until the release policy has an approved owner.

Folder location, filename, modification time, task completion and "newest
file" are captured evidence at most. None of them is a governed transition.

### Evidence required for a governed `published` transition (proposed)

Exact document and revision identity; revision label and date; artifact locator
and content hash; `supersedes` link or explicit first-issue flag; change summary;
author, reviewer and release-authority references; issue purpose; disposition;
exact approval evidence; distribution evidence.

### Current revision

"Current" is derived, never stored as a flag and never inferred from timestamps:
the published revision for a given document and issue purpose that no other
published revision supersedes. Two published revisions for the same document and
purpose with no supersession link between them are a **conflict**, reported as
`conflicting_evidence`. A revision superseded through an explicit link is
`superseded`, not conflicting (graph-view acceptance criterion AC-13).

## Decision 3: Folder conventions are versioned evidence dictionaries

An organization's folder standard maps folder paths to *candidate* document
classes and *candidate* captured states (for example, a markup folder suggests
`wip`; a published-set folder suggests `shared` or `published`; a closeout
submittal folder suggests a record issue). That mapping:

- is a versioned reference dictionary with a content hash, like other reference
  dictionaries in [V1_DOMAIN.md](V1_DOMAIN.md);
- lives in private references for real deployments; the public repository ships
  only a synthetic example dictionary;
- produces candidate facts with a derivation, never confirmed facts, so a
  misfiled document stays findable and is flagged rather than misclassified.

## Decision 4: Reading a source file never locks it

Capturing a drawing must never change what the people working in the document
library can do. Drafters keep CAD files (DWG, DXF) and drawing sets open for
long sessions; an indexer that holds a lock, a check-out or an open handle on
those files blocks saves and co-authoring.

**Proposed rules for every source adapter, drawings first:**

1. **Read-only by construction.** The adapter's credential has read-only
   permission on the library, so a write, lock or check-out is impossible rather
   than merely avoided. The adapter port exposes no write, lock or check-out
   operation.
2. **Never open an editing session.** No check-out, exclusive or shared lock,
   WebDAV lock, co-authoring or editing session, and no sync-client or mapped
   drive that keeps file handles open.
3. **Copy once, then let go.** Read the item's content by its stable item and
   version identifiers through the platform's read API, stream it once into blob
   storage (the existing raw event: blob key, SHA-256, size, media type) and
   close the request. Parsing, OCR, rendering and embedding run on that copy,
   never on the live file.
4. **No write-backs of any kind.** No metadata or property updates, tags,
   comments, format conversions that save to the library, or thumbnail and
   preview generation that writes to the source.
5. **Respect files in use.** A file that is checked out, locked or mid-upload is
   captured as exactly that (a captured-state fact naming the condition and, when
   the source reports it, the holding party). The adapter reads the last
   available version if the platform serves one without a lock, or skips the
   item and retries on the next scheduled pass, never in a tight loop. An
   expected document whose only copy is unavailable resolves to `inaccessible`,
   not `not_found_in_scope`.
6. **Be a quiet neighbor.** Honor throttling responses (`Retry-After`), detect
   change with delta queries and content hashes instead of re-reading unchanged
   files, and run bulk crawls outside working hours.
7. **CAD formats are opaque in v1.** DWG content is binary and proprietary.
   Version 1 records CAD file metadata and hash only and indexes the companion
   published PDF for content. Any later CAD parsing runs offline on the blob copy.

## Absence states this enables (for 0.13.0 and 0.14.0)

When the grammar expects a document class for a scope, the match resolves to
exactly one of: `confirmed` (governed published revision with evidence),
`candidate` (matching evidence, not reviewed), `superseded`, `not_yet_due`,
`inaccessible`, `not_found_in_scope`, `not_applicable`. "Not found" always means
not found within the searched and accessible scope, never "does not exist".

## Schema and migration

- New and changed schemas use the `currentcraft-document/v1` prefix so the 0.10.0
  rename never touches them.
- `Document.source_state` moves to `Revision` as a captured-state fact. Keep the
  `Document` field for one release as deprecated, read-only, and map it onto the
  revision it was captured with; no silent relabeling as observed.
- `Drawing` changes from a two-field scaffold to a facet with a required
  `document_id`. Zero-argument construction is discontinued, matching the V1
  precedent for implemented classes.
- `Submittal` changes from scaffold to the issue-event record above.

## Code plan (after the 0.10.0 read endpoints merge)

1. Add `document_class: Fact[ReferenceCode]` to `Document`; deprecate `transition()` and `source_state`.
2. Add `RevisionState` and `IssuePurpose` references, and `captured_state` on `Revision`.
3. Re-define `Drawing` as a facet; add revision-scoped set membership.
4. Define `Submittal` as an issue event.
5. Wire governed transitions through the existing P4 `StateTransition`, failing closed with `policy not defined` until approved.
6. Add a synthetic folder-convention dictionary and a derivation from path to candidate class and state.
7. Define the read-only source-reader port used by the SharePoint adapter: read by item and version, stream to blob storage, no write, lock or check-out operations.
8. Regenerate contract docs; extend the scaffold generator to mark the new implemented proposals.

### Tests required

- Captured state never produces a `StateTransition`.
- A governed `published` transition without each required evidence item is rejected.
- Current-revision derivation ignores timestamps; two unsuperseded published revisions for one purpose yield `conflicting_evidence`.
- An explicitly superseded revision is `superseded`, not conflicting.
- Set and sheet revisions move independently.
- Folder-derived class and state are always `inferred` candidates with a derivation.
- A misfiled fixture stays retrievable with a candidate-class conflict flag.
- A fake source client that fails on any write, lock, check-out or metadata-update call is never tripped by a full capture run.
- A checked-out or locked fixture yields a captured-state fact and resolves to `inaccessible`; the adapter does not retry within the same pass.
- Content is read exactly once per version; unchanged hashes are not re-downloaded.

## Open decisions for reviewers

| Decision | Proposed owner |
| --- | --- |
| Who may perform governed `published` transitions, per issue purpose | release-policy owner (not yet assigned) |
| Document-class and issue-purpose dictionaries | grammar-profile owner (not yet assigned) |
| Whether the four ISO 19650 states suffice or a local state is needed | both owners |
| Submittal response codes | release-policy owner |
| Sheet-number normalization rules | grammar-profile owner |
| Crawl window and throttling budget for the document library | library administrator |

Until these are decided, everything above that grants a published state stays
fail-closed. Capture, candidate classification and absence reporting do not
wait on them.
