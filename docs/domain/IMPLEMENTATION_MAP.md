# V1 implementation map

Verified remote patch base: `2a6dbfd64745f78a727a3af76c1157de2d869857`.
Implementation uses an exact text snapshot of that base. The associated pull
request records publication and hosted CI status.
No AGENTS.md file exists in the inspected tree.

## Actual path to requested concept

| Actual canonical path under src/app | Proposed work-order concept / action |
| --- | --- |
| domain/shared/scaffold_record.py | retain shared Pydantic scaffold and placeholder compatibility |
| domain/versioning.py | implement existing VersionedEntity; no second version envelope |
| domain/shared/identity.py | add IDs and ExternalReference; none existed |
| domain/shared/facts.py | add missing-value/evidence fact and time value contracts |
| domain/shared/quantities.py | add quantity/unit/source-money values |
| domain/quality/quality_evidence.py | extend existing evidence identity with source assertion data |
| domain/parties/party.py | add shared party identity; Organization remains legacy scaffold |
| domain/workforce/resource.py | add resource behavior; Employee/Contributor/Agent remain in their original modules |
| domain/employee/employee_entity.py | implement existing Employee |
| domain/workforce/contributor.py; agent.py | implement existing sibling resources |
| domain/parties/client.py; vendor.py; four existing vendor modules | implement contextual party classifications |
| domain/engagements/stakeholder_relationship.py; consulting_engagement.py; manufacturer_representation.py | implement existing relationship classes |
| domain/project/project_entity.py; project_phase.py; wbs.py; subsystem.py | implement existing project structure |
| domain/task/task_entity.py | implement existing Task |
| domain/product/product_definition.py; asset_instance.py | implement definition/physical-unit split; Product remains legacy scaffold |
| domain/document/document.py | implement capture only; Drawing remains deferred scaffold |
| domain/materials/bom.py; bom_line.py | implement existing BOM records |
| domain/logistics/shipment.py | implement Shipment and add owned ShipmentLine contract |
| domain/scheduling/calendar_booking.py | implement captured booking |
| domain/coordination/rfi.py | implement existing RFI |
| domain/commercial/commercial_order.py | implement existing independent Order |
| application/process/contracts.py | reuse ProcessExecution, ObjectIncidence, CapabilityBinding, AuthorityRef; do not duplicate in domain |
| application/enterprise/contracts.py; services.py | add allowlisted snapshot/hydration, cross-record checks, denied transition and persistence use cases |
| infrastructure/enterprise/references.py; wiring.py | add explicit-root, hash-pinned file loader and synthetic composition |
| application/persistence; infrastructure/persistence/memory.py | reuse VersionedRecord, UnitOfWorkFactory, MemoryStore and outbox |
| application/messaging/contracts.py | reuse immutable event envelope and domain.stored event; no new broker |
| scripts/gen_agency_contract_docs.py | extend existing schema/docs generator and drift gate |
| scripts/gen_domain_scaffold_docs.py | evolve existing inventory generator; preserve legacy placeholders |
| tests/domain; tests/integration | add focused contract/negative/fixture tests |
| references/public/enterprise.synthetic.v1.json | synthetic declarative units/stage dictionary only |
| examples/domain_bootstrap.py | runnable synthetic fixture; no universal startup hydration |

## Packaging and verification

README/pyproject API-extra mismatch is already repaired on this base: `api`
declares FastAPI, Uvicorn and python-multipart; interfaces/http exists. Do not
apply an obsolete packaging fix. New enterprise packages are explicitly included in the package/export allowlists. Outside-checkout verification also found that the existing application/infrastructure splice packages were omitted from the wheel; their package patterns are included without changing simulator code. CI now installs the declared API extra and test dependencies; generated-doc checks use the tested Pydantic version pinned in requirements-ci.txt. The numeric code and
TensorSpec/TensorRef remain unchanged.

See V1_DOMAIN.md for contract authority, source definitions, open decisions and
migration. Observed checks and exact counts are recorded in V1_HANDOFF.md after
implementation. Local synthetic success is separate from HTTP startup, real
PostgreSQL/NATS integration, hosted CI and deployment.
