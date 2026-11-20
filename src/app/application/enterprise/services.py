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
from app.domain.shared.contexts import SubsystemContext
from .contracts import (EnterpriseSnapshot, ReferenceDictionary, Project, Phase, WBS,
    Subsystem, Task, ProductDefinition, AssetInstance, Document, BOM, Shipment,
    ShipmentLine, QualityEvidence, Party, Consultant, ManufacturerRep, Stakeholder,
    ReferenceSelection, Contract, Revision, System, Location, ReferenceSet,
    ReferenceValue, Client)


class ReferenceError(ValueError):
    """A missing, mistyped or inconsistent reference; nothing is persisted."""


class PolicyNotDefined(PermissionError):
    """Evidence/grants are insufficient without an approved operating policy."""


def payload_digest(dictionary: ReferenceDictionary) -> str:
    """Canonical semantic digest; whole-file byte digest is checked by the loader."""
    data = dictionary.model_dump(mode="json", include={"units", "stages", "process_types"})
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def dictionary_digest(dictionary: ReferenceDictionary) -> str:
    """Bind metadata/provenance as well as semantic entries to the selected model."""
    data = dictionary.model_dump(mode="json")
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_reference_selection(snapshot: EnterpriseSnapshot, selection: ReferenceSelection) -> None:
    """Compare an independently trusted selection, not a hash supplied inside incoming JSON."""
    if not isinstance(selection, ReferenceSelection):
        raise ReferenceError("capture requires an independent verified reference selection")
    selection = ReferenceSelection.model_validate_json(selection.model_dump_json())
    dictionary = snapshot.references
    expected = (dictionary.dictionary_id, dictionary.version, snapshot.reference_sha256,
                payload_digest(dictionary), dictionary_digest(dictionary), snapshot.captured_at)
    actual = (selection.dictionary_id, selection.dictionary_version, selection.file_sha256,
              selection.payload_sha256, selection.dictionary_sha256, selection.as_of)
    if expected != actual:
        raise ReferenceError("verified reference selection/hash/version/time does not match snapshot")
    if not dictionary.valid_window.start <= selection.as_of < dictionary.valid_window.end:
        raise ReferenceError("verified selection outside dictionary validity window")
    if snapshot.reference_verification is not None and snapshot.reference_verification != selection:
        raise ReferenceError("incoming verification receipt differs from independent selection")


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

    def project_of(record):
        value = getattr(record, "project_id", None)
        if isinstance(value, Fact):
            return value.value
        context = getattr(record, "context", None)
        return context.project_id if context is not None else value

    def check_context(context):
        resolve(context.project_id, Project)
        if isinstance(context, SubsystemContext):
            if resolve(context.subsystem_id, Subsystem).project_id != context.project_id:
                raise ReferenceError("context subsystem does not belong to declared project")
        return context.project_id

    support_cache = {}
    def observed_support(eid, active=frozenset()):
        evidence = resolve(eid, QualityEvidence)
        eid = evidence.entity_id
        if eid in active:
            raise ReferenceError("cyclic evidence derivation")
        if eid in support_cache:
            return support_cache[eid]
        if evidence.status == "observed":
            result = True
        elif evidence.status == "unknown":
            result = False
        else:
            supports = [observed_support(i, active | {eid}) for i in evidence.derivation.input_evidence_ids]
            result = any(supports)
        support_cache[eid] = result
        return result

    for record in snapshot.records:
        if isinstance(record, QualityEvidence) and record.derivation is not None:
            observed_support(record.entity_id)  # Resolve every input and detect cycles, even if unused.

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
            if value.value is not None:
                sources = [resolve(eid, QualityEvidence) for eid in value.evidence_ids]
                if value.epistemic_status == "observed" and not any(e.status == "observed" for e in sources):
                    raise ReferenceError("observed fact lacks observed source assertion support")
                if value.epistemic_status == "inferred" and not any(
                    e.status == "inferred" and observed_support(e.entity_id) for e in sources):
                    raise ReferenceError("inferred fact needs an explicit supported inferred assertion")
        if isinstance(value, Quantity) and value.unit not in dictionary.units:
            raise ReferenceError("quantity uses a unit outside selected dictionary/version")

    # Direct links, including optional Fact-valued links, have explicit endpoint types.
    endpoints = {"project_id": Project, "party_id": Party, "provider_party_id": Party,
        "manufacturer_party_id": Party, "representative_party_id": Party,
        "counterparty_id": Party, "client_id": Client,
        "product_definition_id": ProductDefinition, "reference_set_id": ReferenceSet,
        "superseded_by_id": ReferenceValue, "contract_id": Contract,
        "document_id": Document, "supersedes_id": Revision,
        "system_id": System, "parent_wbs_id": WBS, "location_id": Location,
        "subsystem_id": Subsystem, "phase_id": Phase, "wbs_id": WBS,
        "bom_id": BOM, "shipment_id": Shipment, "asset_id": AssetInstance,
        "resource_id": Resource, "task_id": Task}
    for record in snapshot.records:
        for eid in record.evidence_ids:
            resolve(eid, QualityEvidence)
        if isinstance(record, QualityEvidence) and record.recorded_at > snapshot.captured_at:
            raise ReferenceError("evidence was recorded after snapshot capture")
        if isinstance(record, (Stakeholder, Consultant)):
            check_context(record.context)
        if isinstance(record, ManufacturerRep):
            for contact in record.contact_party_ids.value or ():
                resolve(contact, Party)
        for field, cls in endpoints.items():
            if field not in type(record).model_fields:
                continue
            value = getattr(record, field)
            value = value.value if isinstance(value, Fact) else value
            if value is not None:
                target = resolve(value, cls)
                if project_of(record) is not None and project_of(target) is not None:
                    if project_of(record) != project_of(target):
                        raise ReferenceError("cross-project structural link")
        for did in getattr(record, "document_ids", ()):
            document = resolve(did, Document)
            if document.project_id != record.project_id:
                raise ReferenceError("cross-project order/document link")
        for did in getattr(record, "scope_document_ids", ()):
            document = resolve(did, Document)
            if document.project_id != record.project_id:
                raise ReferenceError("cross-project contract/document link")
        if isinstance(record, ReferenceSet):
            if (record.dictionary_id, record.dictionary_version) != (dictionary.dictionary_id, dictionary.version):
                raise ReferenceError("reference set does not match selected dictionary/version")
        if isinstance(record, ReferenceValue) and record.superseded_by_id.value is not None:
            if resolve(record.superseded_by_id.value, ReferenceValue).reference_set_id != record.reference_set_id:
                raise ReferenceError("reference supersession crosses reference sets")
        if isinstance(record, Revision) and record.supersedes_id.value is not None:
            if resolve(record.supersedes_id.value, Revision).document_id != record.document_id:
                raise ReferenceError("revision supersession crosses documents")
        for iid in getattr(record, "impact_ids", ()):
            target = resolve(iid)
            if project_of(target) is not None and project_of(target) != project_of(record):
                raise ReferenceError("cross-project contextual impact")
        if isinstance(record, AssetInstance):
            product = resolve(record.product_definition_id, ProductDefinition)
            if product.is_bulk.value is not False:
                raise ReferenceError("asset requires evidence that its product is non-bulk")
        if isinstance(record, ShipmentLine) and record.asset_id.value is not None:
            if resolve(record.asset_id.value, AssetInstance).project_id != resolve(record.shipment_id, Shipment).project_id:
                raise ReferenceError("shipment asset belongs to another project")

    values = [(r.reference_set_id, r.code.value) for r in snapshot.records
              if isinstance(r, ReferenceValue) and r.code.value is not None]
    if len(values) != len(set(values)):
        raise ReferenceError("duplicate reference code in one set")

    for cls, field in ((Revision, "supersedes_id"), (WBS, "parent_wbs_id"),
                       (ReferenceValue, "superseded_by_id")):
        for record in snapshot.records:
            if not isinstance(record, cls):
                continue
            visited = set()
            current = record
            while current is not None:
                if current.entity_id in visited:
                    raise ReferenceError(f"cycle in {cls.__name__} relationships")
                visited.add(current.entity_id)
                parent = getattr(current, field).value
                current = resolve(parent, cls) if parent is not None else None

    claims = {c.claim_id: c for c in snapshot.approval_claims}
    if len(claims) != len(snapshot.approval_claims) or set(claims) & (set(records) | {snapshot.snapshot_id}):
        raise ReferenceError("duplicate or colliding approval claim ID")
    for record in snapshot.records:
        if isinstance(record, Consultant):
            if len(set(record.approval_claim_ids)) != len(record.approval_claim_ids):
                raise ReferenceError("duplicate engagement approval claim reference")
            for cid in record.approval_claim_ids:
                if cid not in claims or claims[cid].engagement_id != record.entity_id:
                    raise ReferenceError("dangling or mistyped engagement claim reference")
    for claim in snapshot.approval_claims:
        engagement = resolve(claim.engagement_id, Consultant)
        if claim.claim_id not in engagement.approval_claim_ids:
            raise ReferenceError("approval claim missing reciprocal engagement link")
        if check_context(claim.context) != engagement.context.project_id:
            raise ReferenceError("approval claim crosses engagement project context")
        if isinstance(engagement.context, SubsystemContext) and claim.context != engagement.context:
            raise ReferenceError("approval claim exceeds subsystem engagement context")
        if claim.executor_id.value is not None:
            resolve(claim.executor_id.value, Resource)
        if claim.authority.evidence_ref is not None:
            resolve(claim.authority.evidence_ref, QualityEvidence)

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
        if ex_id in seen or ex_id in records or ex_id in claims or ex_id == snapshot.snapshot_id:
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
    """Structural/cross-record hydration; this does not verify original file bytes."""
    snapshot = EnterpriseSnapshot.model_validate(data)
    validate_snapshot(snapshot)
    return snapshot


def hydrate_snapshot_json(data: str | bytes) -> EnterpriseSnapshot:
    """Wire entry point preserves JSON-specific quantity validation before checking links."""
    snapshot = EnterpriseSnapshot.model_validate_json(data)
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


def request_consultant_transition(snapshot: EnterpriseSnapshot, claim_id: UUID,
                                  execution_id: str, target: str) -> None:
    """Consultant claims remain claims; no success path or inferred delegation policy."""
    validate_snapshot(snapshot)
    claim = next((c for c in snapshot.approval_claims if c.claim_id == claim_id), None)
    if claim is None:
        raise ReferenceError("unknown consultant approval claim")
    link = next((x for x in snapshot.executions if x.execution.execution_id == execution_id), None)
    if link is None or link.project_id != claim.context.project_id:
        raise ReferenceError("approval claim/execution context mismatch")
    if isinstance(claim.context, SubsystemContext):
        if link.execution.subsystem_id != str(claim.context.subsystem_id):
            raise ReferenceError("approval claim/execution subsystem mismatch")
    if claim.authority.evidence_ref is None or claim.executor_id.value is None:
        raise PermissionError("consultant claim lacks authority evidence or executor; no grant established")
    request_transition(snapshot, execution_id, target, claim.authority, claim.executor_id.value)


def capture_snapshot(factory: UnitOfWorkFactory, snapshot: EnterpriseSnapshot,
                     expected_version: int | None = None, *,
                     selection: ReferenceSelection | None = None) -> VersionedRecord:
    """Atomic existing aggregate/outbox flow; constructors never persist/dispatch."""
    snapshot = hydrate_snapshot(snapshot.model_dump(mode="json"))
    if selection is None:
        raise ReferenceError("capture requires an independent verified reference selection")
    if not isinstance(selection, ReferenceSelection):
        raise ReferenceError("capture requires an independent verified reference selection")
    selection = ReferenceSelection.model_validate_json(selection.model_dump_json())
    validate_reference_selection(snapshot, selection)
    snapshot = snapshot.model_copy(update={"reference_verification": selection})
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
    """Restore recorded verification provenance; never claim fresh file-byte verification."""
    with factory() as uow:
        record = uow.aggregates.get("enterprise_snapshot", identity)
    if record is None:
        return None
    snapshot = hydrate_snapshot(record.payload)
    if snapshot.reference_verification is None:
        raise ReferenceError("historical capture lacks a verification receipt; explicit migration required")
    validate_reference_selection(snapshot, snapshot.reference_verification)
    return snapshot
