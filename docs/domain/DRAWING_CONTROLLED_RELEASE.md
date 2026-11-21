---
title: Drawing controlled release with acknowledgment
version: 0.11.0-design.1
status: accepted workflow requirement; proposed contracts; not implemented
tags: [currentcraft, domain, drawing, revision, controlled-release]
---

# Drawing controlled release with acknowledgment (option 2)

## Purpose and status

Keep the exact authorized drawing revision accessible to field resources and
visible to the project manager before clearing the drawing prerequisite.
Drawing is separate from Document and owns drawing-specific release,
supersession and distribution behavior. Revision and Submittal are Document
subtypes; the relationship between drawing revisions and the Document-derived
Revision contract remains unresolved.

**Implemented:** this design and the corrected
[lifecycle decision record](DOCUMENT_LIFECYCLE.md) only.
**Not implemented:** proposed fields, contracts, validators, ports, workflow
execution, persistence, notifications or prerequisite evaluator.
**Not claimed:** authority assignments, a deployed workflow, recipient policy,
awareness from delivery, understanding, correct installation, overall
installation readiness or a completed release exit criterion.

The coordinator accepted option 2 on 2026-11-21. Phase 1 is docs only.
Phase 2 requires both the 0.10.0 read-endpoints PR #25 merge and separate
coordinator go-ahead. No HTTP, ingest, deployment or generated OpenAPI changes
belong to this slice. Work-package-specific release (option 3) is deferred.

## Required flow

1. Receive and individually identify the drawing revision, preserving source
   provenance and prior revision history.
2. Validate the revision and obtain an explicit authorized release. Keep latest
   received distinct from current authorized release.
3. Distribute an accessible field rendition linked to the exact native-file
   revision; preserve supersession history.
4. Record acknowledgment of that exact revision by required field recipients.
5. Record evidence of PM visibility, without treating notification delivery as
   proof of awareness.
6. Clear only the drawing prerequisite for installation when the required
   release, acknowledgments and PM visibility evidence are satisfied. Other
   installation prerequisites remain independent.

## Proposed contract vocabulary

All fields below are **not implemented** and are proposed encodings, not newly
accepted operational rules. Requiredness, serialization and subtype
compatibility must be finalized before phase-2 contract acceptance. No extra
fields are implied. Public references are opaque; original source locators and
reversible mappings remain inside the authorized private evidence boundary.
People are resources, never domain objects acted upon by processes.

### EvidenceReference

Each evidence-bearing field refers to one or more records of this shape.
Referencing evidence does not certify its meaning or grant authority.

| Field | Description |
| --- | --- |
| `evidence_id` | Opaque stable identity for this distinct evidence record. |
| `source_reference` | Opaque reference to the source system or source artifact. |
| `source_version_reference` | Exact source version or occurrence reference, preserving provenance rather than guessing currency. |
| `source_locator_reference` | Opaque reference to the original locator held privately; never the original source path or URL in public output. |
| `occurred_at` | Source-reported event time, explicitly unknown if unavailable; never replaced by capture time. |
| `recorded_at` | Time when evidence was recorded, separate from event time. |
| `recorded_by_resource_reference` | Resource or service recording evidence, not an inferred release authority. |

### Drawing release view

| Field | Description |
| --- | --- |
| `drawing_id` | Stable opaque identity of the separate Drawing aggregate. |
| `project_reference` | Explicit opaque project binding; never parsed from a filename. |
| `revision_references` | Individually identified drawing revision records, including history. |
| `latest_received_revision_reference` | Latest evidenced receipt under an explicit ordering basis; unresolved if receipt order is ambiguous and never an authorization pointer. |
| `current_authorized_release_reference` | Current explicit ReleaseRecord reference, or unresolved/absent; not selected merely by receipt time. |
| `release_history_references` | Append-preserving references to authorized release and supersession history. |

### Drawing revision record

This is conceptual, not a decision about inheritance or composition.

| Field | Description |
| --- | --- |
| `revision_id` | Opaque identity of the exact revision, distinct from Drawing identity. |
| `drawing_reference` | Drawing aggregate to which this revision belongs. |
| `native_artifact_reference` | Exact native-file version reference, not a mutable latest-file link. |
| `native_content_sha256` | Hash of captured native bytes; not proof of approval or project identity. |
| `source_revision_label` | Source-reported label; not itself unique identity or authorization. |
| `received_at` | Evidenced receipt time, unknown if unavailable. |
| `receipt_evidence_references` | Receipt, exact source version and locator provenance through EvidenceReference. |
| `predecessor_revision_references` | Evidenced historical revision relationships; receipt of a successor never silently supersedes an authorized release. |
| `validation_evidence_references` | Separate validation evidence; not a substitute for authorization. |

### ReleaseRecord

| Field | Description |
| --- | --- |
| `release_id` | Opaque stable identity of the release decision. |
| `drawing_reference` | Drawing whose release behavior owns this decision. |
| `revision_reference` | Exact revision explicitly authorized. |
| `issue_purpose_reference` | Declared authorization purpose; published state alone cannot imply installation release. |
| `release_authority_resource_reference` | Resource recorded as exercising authority; no actual authority or person is selected here. |
| `authority_evidence_references` | Evidence of that resource's authority for this decision and purpose. |
| `authorization_evidence_references` | Explicit authorization decision evidence, separate from validation and sending. |
| `authorized_at` | Evidenced authorization decision time. |
| `required_field_recipient_resource_references` | Explicit required field-recipient set supplied by authorized policy, never guessed; unknown or empty cannot establish completeness. |
| `recipient_requirement_evidence_references` | Evidence establishing the required-recipient set for this release. |
| `supersedes_release_reference` | Prior release explicitly replaced by this decision, when evidenced; retain its record. |
| `supersession_evidence_references` | Evidence authorizing replacement; a received predecessor link is insufficient. |

### FieldRendition

| Field | Description |
| --- | --- |
| `rendition_id` | Opaque stable identity of the accessible field rendition. |
| `native_revision_reference` | Exact native revision rendered; must agree with the release revision. |
| `rendition_artifact_reference` | Opaque field artifact reference, not a native editing session. |
| `rendition_content_sha256` | Hash of rendition bytes, distinct from the native-file hash. |
| `rendition_link_evidence_references` | Evidence linking rendition to the exact native artifact/version. |

### DistributionRecord

| Field | Description |
| --- | --- |
| `distribution_id` | Opaque identity of an individual sending event. |
| `release_reference` | Exact release being distributed. |
| `rendition_reference` | Exact rendition distributed for that release. |
| `recipient_resource_reference` | Resource targeted by sending; not proof of acknowledgment. |
| `sent_at` | Evidenced sending time, not receipt or awareness time. |
| `sending_evidence_references` | Separate sending evidence; successful delivery alone satisfies neither acknowledgment nor PM visibility. |
| `accessibility_evidence_references` | Evidence of intended recipient access; offline handling remains a policy decision. |

### AcknowledgmentRecord

| Field | Description |
| --- | --- |
| `acknowledgment_id` | Opaque identity of a distinct acknowledgment event. |
| `release_reference` | Exact release requirement acknowledged. |
| `revision_reference` | Exact native revision acknowledged; wrong or superseded revisions cannot satisfy the current requirement. |
| `rendition_reference` | Exact field rendition acknowledged, bound to that native revision. |
| `recipient_resource_reference` | Acknowledging resource, matched to an explicitly required recipient. |
| `acknowledged_at` | Evidenced acknowledgment time, not inferred from sending. |
| `acknowledgment_evidence_references` | Separate explicit acknowledgment evidence; receipt does not prove understanding or correct installation. |

### PMVisibilityRecord

| Field | Description |
| --- | --- |
| `visibility_id` | Opaque identity of distinct PM visibility evidence. |
| `release_reference` | Exact release to which visibility applies. |
| `revision_reference` | Exact revision made visible under the evidence requirement. |
| `pm_resource_reference` | Explicitly designated PM resource; this design assigns nobody. |
| `visible_at` | Evidenced visibility time, not inferred from notification delivery. |
| `visibility_evidence_references` | Separate visibility evidence assessed under agreed policy; sending alone is insufficient and awareness is not inferred. |

### DrawingPrerequisiteEvaluation

| Field | Description |
| --- | --- |
| `evaluation_id` | Opaque identity of the reproducible evaluation, not an installation release token. |
| `drawing_reference` | Drawing prerequisite evaluated. |
| `release_reference` | Exact current authorized release evaluated. |
| `revision_reference` | Exact revision to which all evaluated evidence must bind. |
| `evaluated_at` | Time evidence and current release were evaluated. |
| `requirement_policy_reference` | Versioned, explicitly authorized evidence/recipient policy; unresolved policy prevents clearance. |
| `supporting_evidence_references` | Separate validation, authority, authorization, sending/accessibility, acknowledgment and PM visibility evidence used. |
| `status` | Proposed `uncleared` or `cleared` result; unknown, missing or conflicting requirements/evidence never yield clearance. |
| `unresolved_reasons` | Explicit missing, inaccessible, conflicting or undecided prerequisites; missing evidence does not prove an event never happened. |

## Rules and safety boundaries

Authorization, sending, acknowledgment and PM visibility remain separate evidence
categories even when one artifact contains several explicit events.
Validation and captured lifecycle labels cannot authorize release. A future
governed transition binds exact revision, issue purpose, decision, authority
and evidence. Current authorization is never inferred from the newest file.

Evaluate evidence against the current authorized release and exact revision.
Every explicitly required field resource needs matching acknowledgment and
accessible rendition evidence; separate PM visibility evidence must meet an
established policy. Ambiguous authorization or unknown policy leaves the
prerequisite uncleared.

Preserve earlier releases and evidence after supersession. Never carry
acknowledgments forward to a successor revision. Handling release changes during
distribution must be settled before operational use; this design invents no
escalation, grace period, offline override or recipient substitution.

Clearing this prerequisite neither releases installation work nor reserves
resources. Other prerequisites and human work-release authority are independent.
Decision 4 source-file never-lock rules remain unchanged; render from the
captured copy only.

## Required synthetic acceptance tests (not implemented here)

1. Receive a newer revision while an earlier release remains authorized:
   preserve both, leave authorization unchanged and never authorize by receipt.
2. Reject authorization lacking exact revision, validation, authority or
   authorization evidence; a source publication label is insufficient.
3. A rendition of a different native revision cannot satisfy distribution.
4. Missing required acknowledgments or PM visibility leaves the prerequisite
   uncleared; an unknown recipient set also blocks clearance.
5. Acknowledgment of a different or superseded revision cannot satisfy the
   current release, even by the same resource.
6. Sending alone satisfies neither acknowledgment nor PM visibility; all four
   evidence categories remain independently inspectable.
7. Preserve supersession history; received predecessor links never silently
   change current authorization and earlier acknowledgments never migrate.
8. With an explicit synthetic policy and all matching evidence, clear only
   the drawing prerequisite; other prerequisites and allocations remain
   byte-identical and no installation release is emitted.
9. Missing source timestamps remain unknown, not capture times; original source
   locators and identities never appear on public surfaces.

Use synthetic opaque identities only. These tests demonstrate contract behavior,
not operational effectiveness, actual awareness or correct installation.

## Decisions needed before operational use

Establish release authorities and evidence, required field recipients and policy,
designated PM resources and acceptable visibility evidence. Define escalation,
unavailable-recipient handling, offline work and supersession during distribution.
No actual authorities, recipients or escalation rules are selected here. Resolve
drawing-revision type composition before coding that boundary. Option 3 and
work-package-specific manifests remain deferred.
