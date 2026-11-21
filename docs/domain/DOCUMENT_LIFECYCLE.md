---
title: Drawing representation and document lifecycle
version: 0.11.0-design.1
status: accepted requirements; implementation pending
tags: [currentcraft, domain, document, decision-record]
---

# Drawing representation and document lifecycle

Status: **accepted requirements; implementation pending**, not operating policy.
Implemented: this corrected record only. Not implemented: Document-derived
Revision and Submittal, Drawing aggregate and governed lifecycle.
Not claimed: operational authority, installation readiness or completed exit criteria.
Target release: 0.11.0 (evidence baseline). This page is docs-first: no code
changes until the 0.10.0 document read endpoints merge, because those endpoints
serialize `Document` and would conflict with these contract changes.

It corrects the direction for two rows in [V1_DOMAIN.md](V1_DOMAIN.md), without
claiming older ledgers or runtime contracts are already reconciled:
"Drawing as document" and "Readiness and document lifecycle" (the document half;
work-release readiness stays with the release policy).

## Context

Observed at baseline `8c3f3b8442b400d7ca730d56e23d33aa228cc364` (package 0.9.9):

| Class | State | Relevant behavior |
| --- | --- | --- |
| `Document` | V1 proposal | Long-lived identity: project, name, source version, storage locator, source type label, source state. `transition()` raises `document lifecycle policy is not defined`. |
| `Revision` | V1 proposal | Immutable source-reported revision: label, artifact locator, content hash, `supersedes_id`. Separate from document identity; no inferred current revision. |
| `ReferenceDocument` | V1 proposal | Contextual reference to a document by `document_id`; not a duplicate artifact. |
| `Drawing`, `Submittal`, `Report` | unreviewed scaffolds | Two fields, fail-closed acceptance guard. |

Reference-based Revision implementation is a baseline observation, not authority
to override the accepted subtype decision. The
[dependency graph](DOMAIN_DEPENDENCY_GRAPH.md) is historical context where it
differs from this corrected record.

Downstream releases need this settled: the 0.13.0 expectation grammar generates
expected document classes, and readiness (0.14.0) reports which expected
documents are present, superseded or missing.

## Decision 1: Drawing is separate; Revision and Submittal are Document subtypes

**Accepted requirement, 2026-11-21:** Drawing remains separate from Document
to preserve locality of behavior. Drawing owns drawing-specific release,
supersession and distribution behavior. Revision and Submittal are Document
subtypes. Shared metadata does not require shared inheritance for Drawing.

Document represents project-related material suitable for the document database,
with authorship, revisions, storage references and accountability/evidence
metadata. Revision is individually identifiable and linked to the object it
revises. Submittal has submission and review behavior, not merely an issue event.

The coordinator's accepted 0.11.0 decision supersedes the PR #15 facet proposal.
The relationship between drawing revisions and the Document-derived Revision
contract (inheritance or composition) is unresolved, not selected by this
workflow decision. See [Drawing controlled release](DRAWING_CONTROLLED_RELEASE.md).

### Superseded Decision 1: facet proposal (retained history, not current design)

**Superseded proposal:** keep `Document` as the only document identity. Add a
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

### Superseded sheets-and-sets representation

This sheet/set-as-Document mapping is historical, not current design.
Its mapping onto separate Drawing remains undecided. Revision-scoped membership
remains a proposed constraint, not an implemented contract.

- A **drawing sheet** is a `Document` with class `drawing_sheet` and a `Drawing` facet.
- A **drawing set** is a `Document` with class `drawing_set`.
- Membership is revision-scoped: set revision R includes specific sheet revisions
  (`includes_revision`). A sheet can revise without the set revising, and the
  reverse. Set revision labels never imply sheet revision labels.
- Sheet numbers and disciplines are source facts (observed or inferred with a
  derivation), never parsed into identity.

### Superseded Submittal issue-event-only proposal

The following paragraph and fields are historical, not current proposed fields.
The accepted Document subtype replaces this classification.

A submittal is not a document class. It is an **issue event**: a package of
specific revisions sent for a stated purpose to a recipient, with a recorded
response. Proposed fields: project, issued revision IDs, issue purpose
(dictionary reference), recipient party, issue time, response code (dictionary
reference, unknown until evidenced) and response evidence. The submittal's own
transmittal document, when one exists, is an ordinary `Document`.

## Decision 2: Lifecycle state belongs to Revision, not Document

**Accepted lifecycle direction, not implemented:** state belongs to the
Document-derived Revision. Use the following ISO 19650-style states as reference.
The existing `Document.transition()` failure is baseline behavior to replace
with the accepted revision lifecycle in phase 2, not a permanent design.
Governed transitions remain fail-closed without required evidence and authority.

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

"Current" is proposed to be derived, never inferred from timestamps:
the published revision for a given document and issue purpose that no other
published revision supersedes. Two published revisions for the same document and
purpose with no supersession link between them are a **conflict**, reported as
`conflicting_evidence`. A revision superseded through an explicit link is
`superseded`, not conflicting (graph-view acceptance criterion AC-13).

For Drawing, latest received and current authorized release are distinct.
A received predecessor link alone never revokes or replaces authorization.
Only an explicit authorized decision bound to exact revision evidence changes
release currency; ambiguity blocks prerequisite clearance.

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
- `Drawing` becomes a separate aggregate, not a Document facet.
- `Revision` and `Submittal` become Document subtypes; migration and compatibility
  encodings remain phase-2 work. Preserve persisted identities; changing them
  requires a separate coordinator decision.
- No schemas, constructors, generated references or runtime behavior change in
  this docs-only phase.

## Code plan (after the 0.10.0 read endpoints merge)

Phase 2 also requires explicit coordinator go-ahead after PR #25 merges.
This PR stops at phase 1.

1. Define Document and its Revision/Submittal subtypes with field descriptions and a compatibility plan before replacing the old transition failure.
2. Implement the accepted Revision lifecycle, separate captured state and issue purpose.
3. Implement separate Drawing release, supersession and distribution behavior without implicitly deciding drawing-revision composition.
4. Implement exact-revision rendition, acknowledgment, PM visibility and prerequisite evidence per the linked design.
5. Wire governed transitions through the existing P4 `StateTransition`, failing closed with `policy not defined` until approved.
6. Add a synthetic folder-convention dictionary and a derivation from path to candidate class and state.
7. Define the read-only source-reader port used by the SharePoint adapter: read by item and version, stream to blob storage, no write, lock or check-out operations.
8. Regenerate contract docs; extend the scaffold generator to mark the new implemented proposals.

### Tests required

- Newer receipt alone never authorizes or replaces the current authorized release.
- Missing acknowledgments or PM visibility evidence leave the prerequisite uncleared.
- Wrong or superseded revision acknowledgment never satisfies the current requirement.
- Authorization, sending, acknowledgment and PM visibility retain separate evidence.
- Drawing-prerequisite clearance changes no other prerequisite or resource allocation.
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
| Drawing-revision relationship to Document-derived Revision | coordinator |
| Drawing authority, required recipients and PM visibility evidence policy | coordinator to establish; no assignment inferred |
| Escalation, unavailable recipients, offline work and supersession during distribution | coordinator to establish before operational use |
| Document-class and issue-purpose dictionaries | grammar-profile owner (not yet assigned) |
| Whether the four ISO 19650 states suffice or a local state is needed | both owners |
| Submittal response codes | release-policy owner |
| Sheet-number normalization rules | grammar-profile owner |
| Crawl window and throttling budget for the document library | library administrator |

Until these are decided, everything above that grants a published state stays
fail-closed. Capture, candidate classification and absence reporting do not
wait on them.
