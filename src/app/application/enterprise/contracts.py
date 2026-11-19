"""Allowlisted enterprise boundary. Design: docs/domain/V1_DOMAIN.md."""
from datetime import datetime
from typing import Annotated, Literal, Union, get_args
from uuid import UUID
from pydantic import ConfigDict, Field, model_validator
from app.application.common.contracts import _Frozen
from app.application.process.contracts import ProcessExecution, ProcessType, CapabilityBinding, AuthorityRef
from app.domain.shared.identity import Text, ProjectId, PhaseId, TaskId, ResourceId
from app.domain.shared.facts import Fact, TimeWindow, unknown
from app.domain.shared.contexts import Context
from app.domain.shared.quantities import UnitRef
from app.domain.quality.quality_evidence import QualityEvidence
from app.domain.parties.party import Party
from app.domain.employee.employee_entity import Employee
from app.domain.workforce.contributor import Contributor
from app.domain.workforce.agent import Agent
from app.domain.parties.client import Client
from app.domain.parties.vendor import Vendor
from app.domain.parties.product_only_vendor import ProductOnlyVendor
from app.domain.parties.professional_services_manufacturer_vendor import ProfessionalServicesManufacturerVendor
from app.domain.parties.labor_platform_vendor import LaborPlatformVendor
from app.domain.parties.subcontractor_freelancer_vendor import SubcontractorFreelancerVendor
from app.domain.engagements.stakeholder_relationship import Stakeholder
from app.domain.engagements.consulting_engagement import Consultant
from app.domain.engagements.manufacturer_representation import ManufacturerRep
from app.domain.project.project_entity import Project
from app.domain.project.project_phase import Phase
from app.domain.project.wbs import WBS
from app.domain.project.subsystem import Subsystem
from app.domain.task.task_entity import Task
from app.domain.product.product_definition import ProductDefinition
from app.domain.product.asset_instance import AssetInstance
from app.domain.document.document import Document
from app.domain.materials.bom import BOM
from app.domain.materials.bom_line import BOMLine
from app.domain.logistics.shipment import Shipment, ShipmentLine
from app.domain.scheduling.calendar_booking import CalendarBooking
from app.domain.coordination.rfi import RFI
from app.domain.commercial.commercial_order import Order
from app.domain.commercial.contract import Contract
from app.domain.document.revision import Revision
from app.domain.document.reference_document import ReferenceDocument
from app.domain.project.system import System
from app.domain.geography.location import Location
from app.domain.task.work_item import WorkItem
from app.domain.task.review_item import ReviewItem
from app.domain.parties.organization import Organization
from app.domain.parties.client_division import ClientDivision
from app.domain.parties.manufacturer import Manufacturer
from app.domain.reference.reference_set import ReferenceSet
from app.domain.reference.reference_value import ReferenceValue

SCHEMA_VERSION = "enterprise-v1.1"
# Compile-time allowlist: reference files cannot import, select or execute Python.
Entity = Annotated[Union[
    Party, Employee, Contributor, Agent, Client, Vendor, ProductOnlyVendor,
    ProfessionalServicesManufacturerVendor, LaborPlatformVendor, SubcontractorFreelancerVendor,
    Stakeholder, Consultant, ManufacturerRep, Project, Phase, WBS, Subsystem, Task,
    ProductDefinition, AssetInstance, Document, BOM, BOMLine, Shipment, ShipmentLine,
    CalendarBooking, RFI, Order, QualityEvidence, Contract, Revision, ReferenceDocument,
    System, Location, WorkItem, ReviewItem, Organization, ClientDivision,
    ReferenceSet, ReferenceValue, Manufacturer], Field(discriminator="kind")]
ENTITY_TYPES = get_args(get_args(Entity)[0])


class ReferenceDictionary(_Frozen):
    """Versioned declarative data, with no class names or executable expressions."""
    schema_version: Literal["enterprise-reference-v1.1"] = "enterprise-reference-v1.1"
    dictionary_id: Text
    version: Text
    synthetic: bool = Field(strict=True)
    valid_window: TimeWindow
    provenance: QualityEvidence
    units: tuple[UnitRef, ...]
    stages: tuple[Text, ...]
    process_types: tuple[ProcessType, ...]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256 of canonical JSON units, stages, process_types.")

    @model_validator(mode="after")
    def dictionary_consistency(self):
        if len({u.code for u in self.units}) != len(self.units):
            raise ValueError("duplicate unit code")
        if len(set(self.stages)) != len(self.stages):
            raise ValueError("duplicate stage ID")
        if len({p.code for p in self.process_types}) != len(self.process_types):
            raise ValueError("duplicate process code")
        for u in self.units:
            if (u.dictionary_id, u.dictionary_version) != (self.dictionary_id, self.version):
                raise ValueError("unit dictionary/version mismatch")
        return self


class StageMapping(_Frozen):
    """Explicit project lifecycle phase to execution stage mapping."""
    phase_id: PhaseId
    stage: Text


class CapabilityAssertion(_Frozen):
    """Evidenced capability binding for a specific process type, never permission."""
    process_code: Text
    binding: CapabilityBinding


class ExecutionLink(_Frozen):
    """Business context for the existing process contract; no duplicate process model."""
    project_id: ProjectId
    task_id: TaskId
    phase_id: PhaseId
    execution: ProcessExecution


class ReferenceSelection(_Frozen):
    """Verification receipt, trusted only when independently supplied by configured composition.

    Incoming JSON containing these fields is not proof of verification. Capture
    compares a separately supplied loader result; restore reports recorded provenance.
    """
    dictionary_id: Text
    dictionary_version: Text
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dictionary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Canonical digest of the entire validated dictionary model.")
    as_of: datetime
    method: Literal["raw-sha256-and-semantic/v1"] = "raw-sha256-and-semantic/v1"

    @model_validator(mode="after")
    def aware_selection(self):
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("selection time must be timezone-aware")
        return self


class ConsultantApprovalClaim(_Frozen):
    """Captured claim, always unverified; canonical AuthorityRef is not a verified grant."""
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    claim_id: UUID
    engagement_id: UUID
    context: Context
    authority: AuthorityRef
    executor_id: Fact[ResourceId] = Field(default_factory=unknown)
    authority_evidence_missing_reason: Text | None = "not supplied"
    verification: Literal["unverified_claim"] = "unverified_claim"

    @model_validator(mode="after")
    def explicit_missing_evidence(self):
        if (self.authority.evidence_ref is None) != (self.authority_evidence_missing_reason is not None):
            raise ValueError("authority evidence is supplied or has an explicit missing reason")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler.resolve_ref_schema(handler(core_schema))
        schema.setdefault("allOf", []).append({"oneOf": [
            {"properties": {"authority": {"properties": {"evidence_ref": {"type": "null"}}},
                "authority_evidence_missing_reason": {"type": "string", "pattern": r"\S"}}},
            {"required": ["authority_evidence_missing_reason"], "properties": {
                "authority": {"required": ["evidence_ref"], "properties": {"evidence_ref": {"type": "string"}}},
                "authority_evidence_missing_reason": {"type": "null"}}}
        ]})
        return schema


class EnterpriseSnapshot(_Frozen):
    """Structural capture contract; storage additionally requires independent reference selection."""
    schema_version: Literal["enterprise-v1.1"] = SCHEMA_VERSION
    snapshot_id: UUID
    purpose: Literal["synthetic_fixture", "captured_records"]
    captured_at: datetime
    references: ReferenceDictionary
    reference_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Selected full reference file SHA-256; infrastructure verifies bytes.")
    reference_verification: ReferenceSelection | None = Field(default=None,
        description="Recorded receipt, not independent verification of incoming payload bytes.")
    records: tuple[Entity, ...]
    stage_mappings: tuple[StageMapping, ...] = ()
    capabilities: tuple[CapabilityAssertion, ...] = ()
    executions: tuple[ExecutionLink, ...] = ()
    approval_claims: tuple[ConsultantApprovalClaim, ...] = ()

    @model_validator(mode="after")
    def aware_capture(self):
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return self


CONTRACTS = (ReferenceDictionary, StageMapping, CapabilityAssertion, ExecutionLink,
             ReferenceSelection, ConsultantApprovalClaim, EnterpriseSnapshot)
