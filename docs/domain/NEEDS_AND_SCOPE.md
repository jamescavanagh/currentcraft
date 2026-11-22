---
title: Needs and scope
version: 0.1.0
status: implemented (capture proposal)
tags: [currentcraft, domain, estimation, lsys]
---

# Needs and scope

> [!warning] Status: implemented capture proposal (`v1-proposal`)
> `Need` and `Scope` fill the Estimation / Needs Analysis gap named in [LSYS_DOMAIN_VOCABULARY.md](LSYS_DOMAIN_VOCABULARY.md) so candidate productions p4 and p5 can name real domain objects. They capture what was stated, with evidence or an explicit unknown. They are not estimates, prices, commitments, approved scope or contracts.

## Objects

| Object | Module | Fields beyond `VersionedEntity` |
| --- | --- | --- |
| `Need` | `app.domain.estimation.need` | `project_id`, `statement: Fact[Text]`, `document_ids` (explicit, unique) |
| `Scope` | `app.domain.estimation.scope` | `project_id`, `document_id: Fact[DocumentId]`, `category: Fact[internal_labor / outsourced_labor / vendor_service]`, `statement: Fact[Text]` |
| `Subsystem` (changed) | `app.domain.project.subsystem` | adds `location_id: Fact[UUID]`, default explicit unknown |

## Rules

| # | Rule | Test |
| --- | --- | --- |
| N1 | A need belongs to one project; its statement is an evidenced fact or an explicit unknown, never an empty string | `NeedCapture.test_minimal_need_is_unknown_not_empty` |
| N2 | A need links documents only through explicit, unique `document_ids`; links are never inferred from names or folders | `NeedCapture.test_need_links_documents_explicitly` |
| N3 | Need and Scope grant nothing: no approval, estimate or price field; `require_accepted_definition` always fails; business keys are not identity | `NeedCapture.test_need_grants_nothing` |
| S1 | Scope is labor or service only (internal labor, outsourced labor, vendor service); materials stay on `BOM` and are never mixed in | `ScopeCapture.test_scope_categories_are_labor_or_service_only` |
| S2 | The scope's source document is a fact with evidence or an explicit unknown | `ScopeCapture.test_scope_document_link_is_a_fact` |
| L1 | `Subsystem.location_id` is optional and defaults to unknown; existing subsystems keep their identity and project link unchanged | `SubsystemLocation.test_location_link_defaults_to_unknown_and_identity_is_unchanged` |
| L2 | A known location link needs evidence; in an enterprise snapshot it must resolve to a `Location` in the same project (existing `location_id` endpoint check) | `SubsystemLocation.test_location_link_requires_evidence` |

Tests live in [`tests/domain/test_needs_and_scope.py`](../../tests/domain/test_needs_and_scope.py) and run without skips in `scripts/ci_public.sh`.

## Not claimed

- Need and Scope are not in the enterprise snapshot record set, persistence schema or HTTP API yet.
- No estimating, pricing, approval lineage or sell/cost semantics. A scope's category is a source statement, not an approved labor split.
- `BOM` gains no document link; the p5 `Document` to `BOM` relation remains a reported gap.
- Semantic acceptance of both objects needs coordinator and process-SME review.
