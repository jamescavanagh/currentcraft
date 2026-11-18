"""Deterministic synthetic fixture; no enterprise records, grants or allocations."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from app.application.enterprise.contracts import (CapabilityAssertion, EnterpriseSnapshot,
    ExecutionLink, StageMapping)
from app.application.enterprise.services import hydrate_snapshot
from app.application.process.contracts import CapabilityBinding, ObjectIncidence, ProcessExecution
from app.domain.employee.employee_entity import Employee
from app.domain.parties.party import Party
from app.domain.product.product_definition import ProductDefinition
from app.domain.product.asset_instance import AssetInstance
from app.domain.project.project_entity import Project
from app.domain.project.project_phase import Phase
from app.domain.project.subsystem import Subsystem
from app.domain.task.task_entity import Task
from app.domain.shared.identity import ExternalReference
from .references import load_references

AT = datetime(2000, 1, 2, tzinfo=timezone.utc)
# Whole-file hash pinned in code, independent of untrusted dictionary data.
FIXTURE_REFERENCE_SHA256 = "c80d1f465469877d9f0fe92d79dfc5d5815e1a8530e3bf694ac4c422986c6c74"


def fixture_id(number: int) -> UUID:
    """Stable synthetic IDs only; production identity allocation is not implemented here."""
    return UUID(f"00000000-0000-4000-8000-{number:012d}")


def build_fixture(reference_root: Path) -> EnterpriseSnapshot:
    """Load references, then construct only the independent branches this use case needs."""
    selected = load_references(reference_root, "public/enterprise.synthetic.v1.json",
                               FIXTURE_REFERENCE_SHA256, AT)
    evidence = selected.dictionary.provenance
    def fact(value):
        return {"value": value, "evidence_ids": (evidence.entity_id,)}
    def record(number):
        return {"entity_id": fixture_id(number), "evidence_ids": (evidence.entity_id,)}
    party = Party(**record(2), name=fact("Synthetic participant"))
    employee = Employee(**record(3), party_id=fact(party.entity_id),
                        employment_kind=fact("full_time"), name=fact("Synthetic resource"))
    product = ProductDefinition(**record(4), name=fact("Synthetic device definition"),
                                model=fact("SYNTHETIC-001"), is_bulk=fact(False))
    project = Project(**record(5), name=fact("Synthetic project"),
        external_refs=(ExternalReference(namespace="synthetic.erp.project", key="PRJ-001"),))
    phase = Phase(**record(6), project_id=project.entity_id, name=fact("Synthetic lifecycle phase"))
    subsystem = Subsystem(**record(7), project_id=project.entity_id, name=fact("Synthetic subsystem"))
    task = Task(**record(8), project_id=project.entity_id, name=fact("Synthetic inspection task"),
                subsystem_id=fact(subsystem.entity_id), phase_id=fact(phase.entity_id))
    asset = AssetInstance(**record(9), project_id=project.entity_id,
                          product_definition_id=product.entity_id, serial=fact("SYNTHETIC-SERIAL-001"))
    process = selected.dictionary.process_types[0]
    binding = CapabilityBinding(resource_id=str(employee.entity_id), resource_role="synthetic.executor",
                                evidence_ref=str(evidence.entity_id))
    execution = ProcessExecution(execution_id=str(fixture_id(10)), process=process,
        stage=selected.dictionary.stages[0], subsystem_id=str(subsystem.entity_id),
        incidence=(ObjectIncidence(object_id=str(asset.entity_id), object_kind="asset_instance", effect="reads"),),
        executed_by=(binding,), epistemic_status="simulated", occurred_at=AT,
        source_ref=str(evidence.entity_id))
    snapshot = EnterpriseSnapshot(snapshot_id=fixture_id(11), purpose="synthetic_fixture", captured_at=AT,
        references=selected.dictionary, reference_sha256=selected.sha256,
        records=(evidence, party, employee, product, project, phase, subsystem, task, asset),
        stage_mappings=(StageMapping(phase_id=phase.entity_id, stage=execution.stage),),
        capabilities=(CapabilityAssertion(process_code=process.code, binding=binding),),
        executions=(ExecutionLink(project_id=project.entity_id, task_id=task.entity_id,
                                  phase_id=phase.entity_id, execution=execution),))
    return hydrate_snapshot(snapshot.model_dump(mode="json"))
