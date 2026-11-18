---
title: Domain entity scaffold
version: 0.9.0
status: unreviewed-scaffold
tags: [datamesh, domain, scaffold]
---

# Domain entity scaffold

> [!warning] Scaffold, not a model
> Historical placeholders remain unreviewed. Selected canonical classes now implement the V1 capture proposal in [V1_DOMAIN.md](V1_DOMAIN.md); they remain unapproved for operational use. The generated inventory marks their status.

## What is here

94 historical Pydantic class names under `app.domain`: 82 names from a source class model and 12 additions (product definition and asset instance, four vendor subtypes, shipment, calendar booking, BOM and BOM line, RFI, agent). The full list with paths is the generated [domain scaffold reference](../contracts/DOMAIN_SCAFFOLD.md); its source is [domain_scaffold_manifest.json](domain_scaffold_manifest.json).

Each remaining `unreviewed-scaffold` class has exactly two fields. V1 proposal classes require identity and their documented fields:

| Field | Rule |
| --- | --- |
| `entity_id` | optional UUID; no default identity is invented, and business numbers are rejected |
| `definition_status` | always `unreviewed-scaffold` |

Extra fields are rejected and `require_accepted_definition()` always raises. Unchanged scaffolds never inherit from one another: sharing `ScaffoldRecord` is mechanical, not a claim that the classes share meaning.

## Where it sits

```mermaid
flowchart LR
  RAW["Raw topics"] --> ADP["Adapters"] --> DOM["DomainObject<br/>normalized ingest record"]
  DOM -.->|"explicit mapping, not yet written"| ENT["app.domain scaffolds<br/>canonical entities, unreviewed"]
  ENT -.-> PX["ProcessExecution<br/>object incidence, resource binding"]
```

`DomainObject` (ingestion) is a normalized source record, not the root of these entities. An allowlisted V1 snapshot mapper now exists in app.application.enterprise; automatic source-to-enterprise reconciliation remains future work.

## Direction already fixed by the names

- Employee and Contributor are distinct resources; neither is a subtype of the other.
- Phase is the project lifecycle phase, kept apart from the simulator's physics phase.
- Stakeholder, Consultant and ManufacturerRep are relationships or engagements, not person or organization subtypes. None grants authority by itself.
- Order is a commercial entity, separate from documents that represent it.
- Product splits into ProductDefinition and AssetInstance.
- Vendor has four subtype meanings; whether they may overlap is open.

## Rules

- Pydantic only. No NumPy, no infrastructure imports, no semantic inheritance between unreviewed placeholders. V1 resources share Resource and all V1 entities share VersionedEntity; neither base supplies authority.
- A class leaves scaffold status only through a reviewed definition: meaning and kind, identity and external references, typed attributes with missing-value reasons, field authority, typed relationships, lifecycle, authority, and owned open questions.
- Enterprise-specific records are not published in this tree.

## Example (doctest)

>>> import sys; sys.path.insert(0, "src")
>>> from app.domain.document.drawing import Drawing
>>> p = Drawing()
>>> p.definition_status, p.entity_id
('unreviewed-scaffold', None)
>>> p.require_accepted_definition()
Traceback (most recent call last):
NotImplementedError: Drawing: definition and invariants are not implemented
