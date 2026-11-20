---
title: Enterprise capture contracts, parties, work and documents
version: 0.1.0
tags: [datamesh, domain, proposal]
status: capture-proposal
---

# P0–P3 capture design

This design extends `V1_DOMAIN.md` and the canonical enterprise snapshot. It is a capture proposal, not an approved operating policy. Inputs use opaque UUIDs, namespaced source references, immutable record versions and `Fact` values with evidence or a reason for absence. No constructor performs I/O or authorizes work.

## P0: dictionaries and evidence

`ReferenceDictionary` remains the selected, hash-pinned application dictionary. A `ReferenceSet` identifies a versioned source vocabulary; `ReferenceValue` belongs to one set and has a stable opaque identity and evidenced code. Supersession points to another value in the same set and cannot point to itself; a deprecated value remains readable. Capture requires the independent `ReferenceSelection` from the trusted loader. Restore reports its recorded receipt without claiming fresh verification of source bytes. Record version tracks captured revisions, while valid/effective time describes the source assertion's applicability.

`Fact.epistemic_status` distinguishes observed, inferred and unknown assertions. Known facts require supporting observed evidence or an inferred conclusion whose acyclic derivation reaches observed input. Unknown-only support is insufficient. `QualityEvidence.status` does not mean a reviewer approved an assertion. The reviewed Pydantic and JSON Schema validation boundary remains in [V1_REVIEW_CORRECTIONS.md](V1_REVIEW_CORRECTIONS.md). Schema checks cover local structure; application checks resolve endpoints, source support, dictionary membership and project scope. Neither establishes authorization.

## P1: party and contextual identity

An `Organization` classifies an existing `Party`; organization names remain on `Party` with provenance. A company-specific organization is a configured instance, not a hard-coded type. A `ClientDivision` references its parent client and its own party identity. `Employee` and `Contributor` remain sibling resources. Vendor classifications are contextual, with no inferred mutual exclusivity or authority. `ManufacturerRep` preserves reviewed territory, independently missing agreement-date bounds, typed contact parties and an optional project. `Stakeholder` retains exactly one typed project or subsystem context; adding a commercial contract ID does not establish a new stakeholder scope. Contract and decision context variants remain deferred. Consulting scope and source evidence can be captured while approval claims remain unverified and operational release stays blocked. Personnel/contact access and retention are unresolved, so synthetic fixtures contain no real contact data.

## P2: project work context

`System` and `Location` are project-scoped identities; `Subsystem` may cite a system, but an absent system remains explicitly unknown. A `WBS` may cite a parent WBS and phase. A `Task` may cite WBS, subsystem, phase and location; all known links must resolve to the same project. A phase is a lifecycle phase, not physics or an execution stage. `WorkItem` and `ReviewItem` are task-linked capture records, not new process engines. Baseline and actual date/effort fields remain separate and evidenced; a calendar reservation never authorizes execution. A hierarchy link records source structure and must not be inferred from a task label.

## P3: document and commercial records

`Document` is a long-lived project identity. `Revision` has its own identity, a source label, an optional artifact locator/hash, and a same-document `supersedes` reference; no label or timestamp chooses a current revision. `ReferenceDocument` relates a documented source to a project without making it a commercial agreement. Drawing and PRJDocument semantics remain explicitly unresolved: generic documents can preserve source labels and links, while the old scaffolds remain unaccepted. A `Contract` is a commercial agreement between the company and a client. A subcontract is a separate commercial agreement with an external stakeholder such as a freelancer or subcontractor; the canonical subcontract model and identities are deferred. Contract source identifiers, scope/document links and execution status are captured only when supported. NLP extraction and decomposition of contract contents are future work, with no automatic derivation in this phase. `Order` is independent, with an evidenced kind and optional commercial contract reference. Links to documents are supporting relationships, not approval, spend or procurement release. A source-reported approval or state is a fact about a source, never a permission grant.

## Validation and compatibility

The snapshot allowlist explicitly includes capture classes. Application validation checks typed references, versioned dictionary links, same-project edges, revision cycles and supersession, WBS cycles, and absent authority. New records use the reviewed `enterprise-v1.1` envelope and independent reference selection. Legacy `enterprise-v1` payloads require explicit source-backed migration: status, typed contexts and verification cannot be silently inferred. Changes to a saved entity require the next record version; the persistence store owns CAS and history.

The synthetic test chain is project → contract → purchase order → supporting document → two revisions. The contract source identifier, artifact locators and hashes are unknown with reasons; customer acceptance, baseline adoption, current revision, and procurement or work release are unestablished. Tests verify local invalid values, mistyped/dangling/cross-project links, cycles, schema generation, snapshot round-trip and blocked transitions.

## Decision register

| Decision | Capture treatment | Required owner before operating use |
| --- | --- | --- |
| Reference owner and production dictionary | Synthetic only; no invented reference values | Data governance/source owner |
| Party representation outside a project, vendor overlap | Existing contextual links and explicit unknowns | Commercial and organization owners |
| Personnel/contact access and retention | No real sensitive fixture data | Security and records owners |
| System/WBS nesting and schedule baseline authority | Only source-backed explicit links | Engineering and project management |
| SharePoint identity mapping, revision creation, current set | Keep source references and revision links; never infer current | Document control and SharePoint administration |
| Drawing and PRJDocument mapping | Deferred scaffolds; generic Document capture | Engineering and architecture owners |
| Contract versus subcontract and NLP extraction | Distinct commercial meanings recorded; subcontract identity and extraction deferred | Commercial and architecture owners |
| Contract execution, estimate/baseline and order vocabulary | Independent capture, unknown decisions | Finance and commercial owners |
| Approval, work, procurement and spending authority | Fail closed; no positive transition policy | Designated human reviewers |
| Retention and legal hold | No deletion or expiry operation | Records and legal owners |

The public tree contains only synthetic examples and generic terms. Private source crosswalks, employee names and internal URLs belong outside public artifacts.
