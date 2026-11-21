---
title: Seven frameworks over eleven domains
version: 0.1.0
status: proposed
tags: [currentcraft, domain, standards, infrastructure, references]
---

# Seven frameworks over eleven domains

> [!warning] Status: proposed
> A mapping proposal for infrastructure and vocabulary. It claims no conformity, compliance or certification against any standard, and it adds no domain classes. Coverage labels describe how far a framework's concepts reach a domain, not how well the system implements the standard.

## Why seven, not eleven

The soil-science lens (USDA pedon, profile, horizon, formation processes) was rated a design aid, not a schema, and was ruled out for Drawings. Each domain was then given a purpose-built framework. Seven frameworks are enough: four domains are reached by mapping onto frameworks that already serve another domain. One profile per framework, not one per domain, keeps the reference surface at seven.

Soil-derived analogies stay a separate, unresolved lens. They are not domain classes and are not encoded here.

## The seven frameworks

| ID | Framework | Mathematical lens | Native domain |
| --- | --- | --- | --- |
| F1 | ISO 21502 project management, with ISO 21511 work breakdown | lifecycle states and hierarchical decomposition | Projects |
| F2 | ISO 15489-1 records, ISO 23081 metadata, W3C PROV-O | provenance graph of entity, activity and agent with derivation edges | Working Docs |
| F3 | ISO/IEC 15944-4 business transaction ontology, OASIS UBL | transaction state machine over resources, events and agents | Commercial Orders |
| F4 | ISO/IEC/IEEE 42010 architecture description | typed graph of concerns, viewpoints, views and correspondences | Subsystems |
| F5 | IEC 62381 FAT/FIT/SAT/SIT | test basis and conditions, expected versus observed result, criterion | Site Acceptance Testing |
| F6 | ISO/IEC 26580 feature-based product-line engineering (ISO/IEC DIS 26581 for time, draft only) | feature model; a configuration is valid when it satisfies the model's constraints | Product Features |
| F7 | GS1 EPCIS and CBV | typed visibility events: what, when, where, why | Inventory |

Editions are pinned in each framework profile, not here. No standard text is reproduced; profiles carry concept names and clause references only.

## Eleven domains on seven frameworks

| Domain | Primary | Secondary | Domain objects | Coverage | Gap left by the seven |
| --- | --- | --- | --- | --- | --- |
| Projects | F1 | | `Project`, `Phase`, `WBS`, `Task` | native | none recorded |
| Inventory | F7 | F3 (custody and exchange) | `ProductDefinition`, `AssetInstance`, `BOM`, `BOMLine`, `Shipment`, `ShipmentLine` | native | stock ledger and reservation policy |
| Employees and Contributors | F2 (PROV agent) | F1 (roles and responsibilities) | `Employee`, `Contributor` (resources), `CapabilityAssertion` | mapped, partial | skills levels and verifiable authority; people stay resources, never operands |
| Working Docs | F2 | | `Document` | native | none recorded |
| Drawings | F2 (revision and derivation lineage) | F4 (a drawing as a view of an architecture) | `Drawing` (scaffold) | mapped, partial | native digital model structure, constraints and model views |
| Subsystems | F4 | | `Subsystem` | native | none recorded |
| Product Features | F6 | | none yet | native | objects pending the 0.11 versioned feature graph |
| Site Acceptance Testing | F5 | F2 (test records as evidence) | none yet | native | test-basis, result and acceptance objects |
| Commercial Orders | F3 | | `Order` | native | `Contract` remains a scaffold |
| Clients | F3 (party and agent roles) | | `Client` on `Party` | mapped | registry-sourced legal identity and parent links |
| Estimation / Needs Analysis | F1 (planning and business case) | F3 (planning and identification phases) | none yet | mapped, partial | estimate class thresholds and requirement quality |
| Timecards (cross-cutting) | F2 (activity start and end, capture) | F3 (time as a consumed resource) | `TimeCard` (scaffold) | mapped | not a domain; recorded-versus-valid time is handled by reference validity windows |

Each domain has exactly one primary framework. A secondary framework is used only where listed. A partial gap is recorded, not filled by an eighth framework, until the coordinator decides otherwise.

## Infrastructure

```mermaid
flowchart LR
  REF["references/ (public, synthetic)<br/>references/private/ (git-ignored)"] -->|"hash-pinned JSON"| LOAD["infrastructure loader<br/>explicit root, SHA-256, as_of"]
  LOAD -->|"validated profile + selection"| MAP["application mapper<br/>allowlisted domain classes"]
  MAP -->|"concept to object mapping"| DOM["app.domain objects<br/>no I/O"]
  MAP -->|"coverage, gaps"| LSYS["expectation grammar<br/>alphabet limited to mapped objects"]
```

| Concern | Placement | Rule |
| --- | --- | --- |
| Framework profile | one JSON reference file per framework, under `references/` | carries `framework_id`, framework edition, `profile_version`, `source_digest`, concept-to-domain-object mappings and coverage labels |
| Loading | infrastructure, reusing the hash-pinned pattern in `app.infrastructure.enterprise.references` | explicit absolute root, path inside root, size limit, SHA-256 match, closed JSON, timezone-aware `as_of` inside the validity window |
| Provenance | the loader's selection record travels with every mapped result | dictionary id, version, file and payload digests, `as_of` |
| Mapping | application | concepts map only into allowlisted domain classes; no class name in a profile is imported or executed |
| Domain | `app.domain` | Pydantic only, no file access, no NumPy or Torch |
| Private mappings | `references/private/`, git-ignored, server-side | enterprise terms, codes and file names never enter public profiles |
| Grammar | expectation grammar | may grow symbols only for domains with mapped objects; gap domains grow nothing |

## Proposed acceptance

1. Every domain resolves to exactly one primary framework, and every framework ID is one of F1 to F7.
2. Coverage labels are limited to `native`, `mapped`, `mapped, partial`.
3. A profile whose SHA-256 or payload digest differs from the pinned value is rejected.
4. A profile naming a class outside the allowlist is rejected.
5. Domains without domain objects produce no grammar symbols.
6. Public profiles contain no private terms (checked by `dmgov release --terms`).

## Decisions needed

1. Whether framework profiles reuse the existing reference dictionary schema or get their own schema. The existing dictionary and the path-rule projection already keep distinct schemas and digest semantics; a third schema needs the same separation.
2. Whether the four partial gaps (people authority, digital drawing models, client legal identity, estimate classes) stay recorded gaps or justify an eighth framework.
3. Whether Timecards' valid-versus-recorded time needs more than reference validity windows.

## Not claimed

- No framework profile, loader change or mapper exists yet.
- A coverage label is not conformity to the standard.
- Mappings onto a secondary framework are interpretations for vocabulary, not equivalences.
- See [L-system domain vocabulary](LSYS_DOMAIN_VOCABULARY.md) for the grammar alphabet these mappings constrain.
