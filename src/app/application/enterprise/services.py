"""Hydrate, validate and capture through existing ports; never grant guessed rights."""
import hashlib
import json
from uuid import UUID
from pydantic import BaseModel
from app.application.persistence.contracts import VersionedRecord, VersionConflict
from app.application.persistence.ports import UnitOfWorkFactory
from app.application.messaging.contracts import make_event
from app.application.process.lifecycle import derive_object_events
from app.application.process.contracts import AuthorityRef
from app.domain.shared.facts import Fact
from app.domain.shared.quantities import Quantity
from app.domain.workforce.resource import Resource
from .contracts import (EnterpriseSnapshot, ReferenceDictionary, Project, Phase, WBS,
    Subsystem, Task, ProductDefinition, AssetInstance, Document, BOM, Shipment,
    ShipmentLine, QualityEvidence, Party)


class ReferenceError(ValueError):
    """A missing, mistyped or inconsistent reference; nothing is persisted."""


class PolicyNotDefined(PermissionError):
    """Evidence/grants are insufficient without an approved operating policy."""


def payload_digest(dictionary: ReferenceDictionary) -> str:
    """Canonical semantic digest; whole-file byte digest is checked by the loader."""
    data = dictionary.model_dump(mode="json", include={"units", "stages", "process_types"})
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _walk(value):
    yield value
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _walk(getattr(value, name))
    elif isinstance(value, tuple):
        for item in value:
            yield from _walk(item)


def validate_snapshot(snapshot: EnterpriseSnapshot) -> None:
    """Validate references and technical invariants, without approving business policy."""
    records = {r.entity_id: r for r in snapshot.records}
    if len(records) != len(snapshot.records) or snapshot.snapshot_id in records:
        raise ReferenceError("duplicate or colliding internal IDs")

    def resolve(value, cls=BaseModel):
        try:
            identity = value if isinstance(value, UUID) else UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ReferenceError("enterprise references must use opaque UUIDs") from exc
        record = records.get(identity)
        if record is None or not isinstance(record, cls):
            raise ReferenceError(f"dangling or mistyped {cls.__name__} reference: {identity}")
        return record

    dictionary = snapshot.references
    if payload_digest(dictionary) != dictionary.payload_sha256:
        raise ReferenceError("reference payload hash mismatch")
    if not dictionary.valid_window.start <= snapshot.captured_at < dictionary.valid_window.end:
        raise ReferenceError("reference snapshot outside validity window")
    if dictionary.provenance != resolve(dictionary.provenance.entity_id, QualityEvidence):
        raise ReferenceError("reference provenance does not match canonical evidence")
    if snapshot.purpose == "captured_records" and dictionary.synthetic:
        raise ReferenceError("synthetic dictionary cannot support captured business records")
    for value in _walk(snapshot):
        if isinstance(value, Fact):
            for eid in value.evidence_ids:
                resolve(eid, QualityEvidence)
        if isinstance(value, Quantity) and value.unit not in dictionary.units:
            raise ReferenceError("quantity uses a unit outside selected dictionary/version")

    # Direct links, including optional Fact-valued links, have explicit endpoint types.
    endpoints = {"project_id": Project, "party_id": Party, "provider_party_id": Party,
        "manufacturer_party_id": Party, "representative_party_id": Party,
        "counterparty_id": Party, "product_definition_id": ProductDefinition,
        "subsystem_id": Subsystem, "phase_id": Phase, "wbs_id": WBS,
        "bom_id": BOM, "shipment_id": Shipment, "asset_id": AssetInstance,
        "resource_id": Resource, "task_id": Task}
    for record in snapshot.records:
        for eid in record.evidence_ids:
            resolve(eid, QualityEvidence)
        if isinstance(record, QualityEvidence) and record.recorded_at > snapshot.captured_at:
            raise ReferenceError("evidence was recorded after snapshot capture")
        for field, cls in endpoints.items():
            if field not in type(record).model_fields:
                continue
            value = getattr(record, field)
            value = value.value if isinstance(value, Fact) else value
            if value is not None:
                target = resolve(value, cls)
                if hasattr(record, "project_id") and hasattr(target, "project_id"):
                    if record.project_id != target.project_id:
                        raise ReferenceError("cross-project structural link")
        for did in getattr(record, "document_ids", ()):
            document = resolve(did, Document)
            if document.project_id != record.project_id:
                raise ReferenceError("cross-project order/document link")
        for iid in getattr(record, "impact_ids", ()):
            target = resolve(iid)
            if hasattr(target, "project_id") and target.project_id != record.project_id:
                raise ReferenceError("cross-project contextual impact")
        if isinstance(record, AssetInstance):
            product = resolve(record.product_definition_id, ProductDefinition)
            if product.is_bulk.value is not False:
                raise ReferenceError("asset requires evidence that its product is non-bulk")
        if isinstance(record, ShipmentLine) and record.asset_id.value is not None:
            if resolve(record.asset_id.value, AssetInstance).project_id != resolve(record.shipment_id, Shipment).project_id:
                raise ReferenceError("shipment asset belongs to another project")

    mappings = {}
    for mapping in snapshot.stage_mappings:
        resolve(mapping.phase_id, Phase)
        if mapping.phase_id in mappings or mapping.stage not in dictionary.stages:
            raise ReferenceError("duplicate phase mapping or unknown stage")
        mappings[mapping.phase_id] = mapping.stage
    processes = {p.code: p for p in dictionary.process_types}
    assertions = set()
    for assertion in snapshot.capabilities:
        binding = assertion.binding
        resolve(binding.resource_id, Resource)
        if not binding.resource_role.strip() or assertion.process_code not in processes:
            raise ReferenceError("unknown process or blank capability role")
        resolve(binding.evidence_ref, QualityEvidence)
        key = (assertion.process_code, binding.resource_id, binding.resource_role, binding.evidence_ref)
        if key in assertions:
            raise ReferenceError("duplicate capability assertion")
        assertions.add(key)
    seen = set()
    for link in snapshot.executions:
        ex = link.execution
        try:
            ex_id = UUID(ex.execution_id)
        except ValueError as exc:
            raise ReferenceError("execution requires an opaque UUID") from exc
        if ex_id in seen or ex_id in records or ex_id == snapshot.snapshot_id:
            raise ReferenceError("duplicate or colliding execution ID")
        seen.add(ex_id)
        task = resolve(link.task_id, Task)
        phase = resolve(link.phase_id, Phase)
        resolve(link.project_id, Project)
        if task.project_id != link.project_id or phase.project_id != link.project_id:
            raise ReferenceError("execution context crosses projects")
        if task.phase_id.value is not None and task.phase_id.value != phase.entity_id:
            raise ReferenceError("execution phase differs from task phase")
        if mappings.get(phase.entity_id) != ex.stage:
            raise ReferenceError("explicit lifecycle-phase/execution-stage mapping required")
        if processes.get(ex.process.code) != ex.process:
            raise ReferenceError("process does not match selected reference definition")
        if ex.subsystem_id is not None:
            subsystem = resolve(ex.subsystem_id, Subsystem)
            if subsystem.project_id != link.project_id or task.subsystem_id.value != subsystem.entity_id:
                raise ReferenceError("execution/task subsystem mismatch")
        if ex.at_buffer is not None:
            raise ReferenceError("buffer definitions are outside this minimal slice")
        if ex.occurred_at is None or ex.occurred_at.tzinfo is None or ex.occurred_at.utcoffset() is None:
            raise ReferenceError("execution requires a timezone-aware source timestamp")
        if ex.occurred_at > snapshot.captured_at:
            raise ReferenceError("execution occurred after capture")
        resolve(ex.source_ref, QualityEvidence)
        if ex.decision is not None:
            raise PolicyNotDefined("operational decisions require approved readiness/authority policy")
        if not ex.executed_by:
            raise ReferenceError("fixture executions require evidenced capability bindings")
        for binding in ex.executed_by:
            resolve(binding.resource_id, Resource)
            key = (ex.process.code, binding.resource_id, binding.resource_role, binding.evidence_ref)
            if key not in assertions:
                raise ReferenceError("execution capability lacks a matching evidenced assertion")
        for incidence in ex.incidence:
            target = resolve(incidence.object_id)
            if isinstance(target, (Resource, Party)) or target.kind in {
                "client", "vendor", "product_only_vendor", "labor_platform_vendor",
                "professional_services_manufacturer_vendor", "subcontractor_freelancer_vendor",
                "stakeholder", "consultant", "manufacturer_rep"}:
                raise ReferenceError("parties/resources/contextual roles are not process operands")
            if hasattr(target, "project_id") and target.project_id != link.project_id:
                raise ReferenceError("process operand belongs to another project")
            if incidence.object_kind is not None and incidence.object_kind != target.kind:
                raise ReferenceError("incidence kind does not match canonical record")
            if incidence.origin_buffer is not None or incidence.destination_buffer is not None:
                raise ReferenceError("custody/holding workflow is undefined")
            if isinstance(target, AssetInstance) and incidence.effect in {"produces", "consumes"}:
                raise ReferenceError("asset capture/transfer cannot create or consume physical units")
    # Existing lifecycle replay enforces state continuity and no duplicate births/deaths.
    produced = {UUID(i.object_id) for x in snapshot.executions for i in x.execution.incidence if i.effect == "produces"}
    derive_object_events((x.execution for x in snapshot.executions),
                         preexisting=(str(i) for i in records if i not in produced))


def hydrate_snapshot(data: dict) -> EnterpriseSnapshot:
    """Only discriminated, statically allowlisted entity types can hydrate."""
    snapshot = EnterpriseSnapshot.model_validate(data)
    validate_snapshot(snapshot)
    return snapshot


def request_transition(snapshot: EnterpriseSnapshot, execution_id: str, target: str,
                       authority: AuthorityRef | None = None, executor_id: UUID | None = None) -> None:
    """Deliberately no success path: operating policies are not supplied or approved."""
    validate_snapshot(snapshot)
    link = next((x for x in snapshot.executions if x.execution.execution_id == execution_id), None)
    if link is None:
        raise ReferenceError("unknown execution")
    if authority is None:
        raise PermissionError("transition blocked: scoped human authority is missing")
    if authority.evidence_ref is None or executor_id is None:
        raise PermissionError("transition blocked: decision evidence and explicit executor required")
    records = {r.entity_id: r for r in snapshot.records}
    try:
        evidence = records.get(UUID(authority.evidence_ref))
    except ValueError as exc:
        raise PermissionError("transition blocked: invalid authority evidence reference") from exc
    if not isinstance(evidence, QualityEvidence) or evidence.status != "observed":
        raise PermissionError("transition blocked: observed decision evidence required")
    executor = records.get(executor_id)
    if executor is None or executor.kind not in {"employee", "contributor"}:
        raise PermissionError("transition blocked: human executor required")
    # Existing contracts lack holder identity, context, validity and revocation semantics.
    # Even a plausible role/evidence string is never treated as a grant.
    raise PolicyNotDefined("transition blocked: approved authority/readiness policy is not defined")


def capture_snapshot(factory: UnitOfWorkFactory, snapshot: EnterpriseSnapshot,
                     expected_version: int | None = None) -> VersionedRecord:
    """Atomic existing aggregate/outbox flow; constructors never persist/dispatch."""
    snapshot = hydrate_snapshot(snapshot.model_dump(mode="json"))
    version = (expected_version or 0) + 1
    record = VersionedRecord(aggregate_type="enterprise_snapshot", aggregate_id=snapshot.snapshot_id,
        version=version, schema_version=snapshot.schema_version, payload=snapshot.model_dump(mode="json"),
        recorded_at=snapshot.captured_at)
    synthetic = snapshot.purpose == "synthetic_fixture"
    event = make_event(topic=f"stored/enterprise_snapshot/{snapshot.snapshot_id}", kind="domain.stored",
        source="enterprise", epistemic_status="simulated" if synthetic else "computed",
        sim_time=0.0 if synthetic else None, occurred_at=snapshot.captured_at,
        payload={"snapshot_id": str(snapshot.snapshot_id), "version": version,
                 "digest": hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()})
    with factory() as uow:
        result = uow.aggregates.save(record, expected_version)
        for entity in snapshot.records:
            payload = entity.model_dump(mode="json")
            prior = uow.aggregates.get("enterprise_entity", entity.entity_id)
            if prior is not None and prior.payload == payload:
                continue
            if prior is not None and prior.payload.get("kind") != entity.kind:
                raise VersionConflict("entity kind change requires an explicit migration")
            expected_entity_version = prior.version if prior is not None else None
            if entity.record_version != (expected_entity_version or 0) + 1:
                raise VersionConflict("entity payload/version conflict; supply the next immutable revision")
            uow.aggregates.save(VersionedRecord(aggregate_type="enterprise_entity",
                aggregate_id=entity.entity_id, version=entity.record_version,
                schema_version=entity.schema_version, payload=payload,
                recorded_at=snapshot.captured_at), expected_entity_version)
        uow.outbox.add(event, snapshot.captured_at)
        uow.commit()
    return result


def restore_snapshot(factory: UnitOfWorkFactory, identity: UUID) -> EnterpriseSnapshot | None:
    with factory() as uow:
        record = uow.aggregates.get("enterprise_snapshot", identity)
    return None if record is None else hydrate_snapshot(record.payload)
