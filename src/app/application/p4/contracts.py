"""P4 design contracts for Workflow I. No I/O, ERP schema or operating grant.

These application contracts precede implementation of the 17 domain scaffolds.
Design source: docs/domain/P4_DESIGN_CONTRACTS.md.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Literal, Mapping
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must have a timezone")
    return value


class VersionRef(Frozen):
    identity: UUID
    version: int = Field(ge=1, strict=True)


class WorkflowIIdentity(Frozen):
    project_id: UUID
    logical_product_id: UUID
    run_id: UUID
    product: VersionRef
    evaluation: VersionRef
    graph: VersionRef
    delivery_attempt_id: UUID | None = None

    @model_validator(mode="after")
    def distinct_identifiers(self):
        ids = [self.project_id, self.logical_product_id, self.run_id,
               self.product.identity, self.evaluation.identity, self.graph.identity]
        if self.delivery_attempt_id is not None:
            ids.append(self.delivery_attempt_id)
        if len(set(ids)) != len(ids):
            raise ValueError("independent identities must not alias")
        return self


class ReportCalendar(Frozen):
    calendar_id: str = Field(min_length=1)
    version: int = Field(ge=1, strict=True)
    timezone_name: str
    cutoff_local: time

    @field_validator("timezone_name")
    @classmethod
    def known_timezone(cls, name: str):
        try:
            ZoneInfo(name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be an IANA timezone") from exc
        return name

    @model_validator(mode="after")
    def local_clocks(self):
        if self.cutoff_local.tzinfo is not None:
            raise ValueError("calendar clock times must be local and timezone-free")
        return self

    def assigned_source_time(self, source_date: date) -> datetime:
        """Only for known date-only inputs; caller retains original date and 'assigned' precision."""
        return datetime.combine(source_date, time(9, 0), tzinfo=ZoneInfo("America/Los_Angeles"))


class GenerationRequest(Frozen):
    schema_version: Literal["workflow-i-request/v1"] = "workflow-i-request/v1"
    request_key: str = Field(min_length=1, max_length=120)
    project_id: UUID
    logical_product_id: UUID
    mode: Literal["initial", "refresh", "reproduce"]
    window_start: datetime
    cutoff_exclusive: datetime
    calendar_id: str = Field(min_length=1)
    calendar_version: int = Field(ge=1, strict=True)
    output_profile: str = Field(min_length=1)
    source_profile: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    calculation_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    pinned_manifest_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def request_bounds(self):
        if aware(self.window_start) >= aware(self.cutoff_exclusive):
            raise ValueError("cutoff must follow window start")
        if (self.mode == "reproduce") != (self.pinned_manifest_digest is not None):
            raise ValueError("reproduction requires pinned inputs; other modes cannot pin them")
        return self

    def fingerprint(self) -> str:
        """Versioned canonical JSON, excluding only the transport request key."""
        values = self.model_dump(mode="json", exclude={"request_key"})
        for field in ("window_start", "cutoff_exclusive"):
            values[field] = getattr(self, field).astimezone(timezone.utc).isoformat(timespec="microseconds")
        canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return sha256(canonical.encode("utf-8")).hexdigest()

    def matches_retry(self, other: "GenerationRequest") -> bool:
        if self.request_key != other.request_key:
            raise ValueError("different request keys")
        if self.fingerprint() != other.fingerprint():
            raise ValueError("request key reused with conflicting parameters")
        return True


class ExtractionManifest(Frozen):
    extraction_id: UUID
    source_profile: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    capability: Literal["stable_snapshot", "change_token", "best_effort"]
    snapshot_token: str | None = None
    page_count: int = Field(ge=1, strict=True)
    complete: bool
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    window_start: datetime
    cutoff_exclusive: datetime
    received_at: datetime
    limitation: str | None = None

    @model_validator(mode="after")
    def consistency(self):
        for value in (self.window_start, self.cutoff_exclusive, self.received_at):
            aware(value)
        if self.window_start >= self.cutoff_exclusive:
            raise ValueError("invalid extraction window")
        if self.capability != "best_effort" and not self.snapshot_token:
            raise ValueError("consistent extraction needs a snapshot/change token")
        if self.capability == "best_effort" and not self.limitation:
            raise ValueError("best-effort source must declare its limitation")
        return self


def resume_action(saved: ExtractionManifest, current: ExtractionManifest) -> Literal["reuse", "refetch", "block"]:
    """Reuse only byte-equivalent complete snapshots; refetch all pages after a changed token."""
    same_context = (saved.source_profile == current.source_profile and
                    saved.contract_version == current.contract_version and
                    saved.window_start == current.window_start and
                    saved.cutoff_exclusive == current.cutoff_exclusive)
    if not same_context or not current.complete or not saved.complete:
        return "block"
    if saved.capability != current.capability:
        return "block"
    if saved.capability == "best_effort":
        return "reuse" if saved.extraction_id == current.extraction_id and saved.content_digest == current.content_digest else "block"
    if saved.snapshot_token != current.snapshot_token:
        return "refetch"
    if saved.content_digest != current.content_digest:
        return "block"  # Same token with changed bytes violates the source's consistency claim.
    if saved.extraction_id == current.extraction_id and saved.content_digest == current.content_digest and saved.page_count == current.page_count:
        return "reuse"
    return "refetch"  # Never stitch pages; full new extraction and validation required.


class Association(Frozen):
    source_id: UUID
    target_id: UUID
    relation: Literal["project", "wbs", "order", "order_line", "cost_code", "bom_line"]
    basis: Literal["explicit_source", "reviewed_mapping", "hil_confirmed", "candidate"]
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    rule_version: str | None = None
    label_event_id: UUID | None = None
    conflicting_evidence_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def association_basis(self):
        if self.source_id == self.target_id or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("invalid association endpoints or duplicate evidence")
        if self.basis == "reviewed_mapping" and not self.rule_version:
            raise ValueError("reviewed mappings require a rule version")
        if self.basis == "hil_confirmed" and self.label_event_id is None:
            raise ValueError("human confirmation requires a label event")
        if self.basis != "hil_confirmed" and self.label_event_id is not None:
            raise ValueError("label belongs to HIL confirmation")
        return self

    @property
    def confirmed(self) -> bool:
        return self.basis != "candidate" and not self.conflicting_evidence_ids


class MeasureDefinition(Frozen):
    code: Literal["so_sell", "po_ordered", "labor_recorded_hours", "category_total"]
    category: Literal["hourly_labor", "lump_sum_labor", "product", "outsourced_labor", "integration_material"]
    grain: Literal["line", "time_entry", "project_category"]
    unit: str = Field(min_length=1)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    inclusion_rule: str = Field(min_length=1)
    duplicate_rule: Literal["stable_source_id_and_version", "block_ambiguous"]
    provenance_required: bool = True
    unavailable_reason: str = Field(min_length=1)
    definition_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_measure(self):
        if self.code == "labor_recorded_hours" and (self.unit != "hour" or self.currency is not None or self.grain != "time_entry"):
            raise ValueError("recorded hours require time-entry grain and hour unit")
        if self.code != "labor_recorded_hours" and self.currency is None:
            raise ValueError("monetary measures require currency")
        return self


class MeasureInput(Frozen):
    source_id: UUID
    source_version: str = Field(min_length=1)
    category: str
    amount: Decimal
    unit: str
    currency: str | None = None
    evidence_id: UUID
    confirmed_project_id: UUID | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def exact_decimal(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("amount must be exact source decimal, not float")
        return value


def aggregate_measure(definition: MeasureDefinition, inputs: tuple[MeasureInput, ...], project_id: UUID) -> Decimal | None:
    """Return None when no confirmed inputs; incompatible/ambiguous inputs block the aggregate."""
    seen: dict[UUID, MeasureInput] = {}
    total = Decimal(0)
    matched = False
    for item in inputs:
        if item.confirmed_project_id != project_id or item.category != definition.category:
            continue
        matched = True
        if item.unit != definition.unit or item.currency != definition.currency:
            raise ValueError("unit/currency collision in aggregate")
        if item.source_id in seen:
            if seen[item.source_id] != item:
                raise ValueError("ambiguous duplicate source record")
            continue
        seen[item.source_id] = item
        total += item.amount
    return total if matched else None


RequirementClass = Literal["mandatory", "conditional", "informational"]
Applicability = Literal["yes", "no", "unknown"]
EvidenceCondition = Literal["sufficient", "missing", "conflicting", "stale", "fails"]
Result = Literal["pass", "fail", "missing", "conflicting", "stale", "not_applicable"]


class CriterionAssessment(Frozen):
    requirement: RequirementClass
    applicability: Applicability
    evidence: EvidenceCondition
    result: Result

    @model_validator(mode="after")
    def result_matches_evidence(self):
        if self.requirement == "mandatory" and self.applicability == "no":
            raise ValueError("mandatory criterion cannot be inapplicable")
        if self.applicability == "no":
            expected = "not_applicable"
        elif self.applicability == "unknown":
            expected = "missing"
        else:
            expected = {"sufficient": "pass", "fails": "fail", "missing": "missing",
                        "conflicting": "conflicting", "stale": "stale"}[self.evidence]
        if self.result != expected:
            raise ValueError("result does not match applicability/evidence")
        return self

    @property
    def blocks_transition(self) -> bool:
        return self.requirement != "informational" and self.result not in ("pass", "not_applicable")


class AppliedTransition(Frozen):
    """Replay index referencing the committed execution, not an independent event log."""
    run_id: UUID
    sequence: int = Field(ge=1, strict=True)
    execution_id: str = Field(min_length=1)
    from_state: Literal["Requested", "In Process", "Prepared", "Failure", "Published"]
    to_state: Literal["Requested", "In Process", "Prepared", "Failure", "Published"]
    gate_decision_id: UUID | None = None
    expected_run_version: int = Field(ge=1, strict=True)
    committed_run_version: int = Field(ge=2, strict=True)

    @model_validator(mode="after")
    def contiguous_version(self):
        if self.committed_run_version != self.expected_run_version + 1:
            raise ValueError("transition version must advance by one")
        return self


class CommittedExecutionRef(Frozen):
    """Read-only reference to a committed canonical ProcessExecution, never a second execution."""
    execution_id: str = Field(min_length=1)
    run_id: UUID
    gate_decision_id: UUID | None = None
    target: VersionRef
    evidence: tuple[VersionRef, ...] = ()


class CommittedGateDecisionRef(Frozen):
    """Integrity link; full actor/authority/purpose record belongs to canonical GateDecision."""
    decision_id: UUID
    execution_id: str = Field(min_length=1)
    run_id: UUID
    evaluation: VersionRef
    target: VersionRef


def replay_transitions(run_id: UUID, transitions: tuple[AppliedTransition, ...],
                       committed_executions: Mapping[str, CommittedExecutionRef],
                       committed_decisions: Mapping[UUID, CommittedGateDecisionRef] | None = None) -> str:
    state, version, used = "Requested", 1, set()
    decisions = committed_decisions or {}
    for index, step in enumerate(transitions, 1):
        execution = committed_executions.get(step.execution_id)
        if (step.run_id != run_id or step.sequence != index or step.execution_id in used or
                execution is None or execution.run_id != run_id or execution.execution_id != step.execution_id):
            raise ValueError("missing, duplicate or uncommitted execution in history")
        if execution.gate_decision_id != step.gate_decision_id:
            raise ValueError("transition and execution disagree on gate decision")
        if step.gate_decision_id is not None:
            decision = decisions.get(step.gate_decision_id)
            if (decision is None or decision.run_id != run_id or decision.execution_id != step.execution_id or
                    decision.decision_id != step.gate_decision_id or decision.target != execution.target):
                raise ValueError("gate decision reference is missing or inconsistent")
        if step.from_state != state or step.expected_run_version != version:
            raise ValueError("history has a state/version gap")
        if (state, step.to_state) not in {("Requested", "In Process"), ("Requested", "Failure"),
            ("In Process", "Prepared"), ("In Process", "Failure"), ("Prepared", "Published"),
            ("Prepared", "Failure"), ("Failure", "In Process")}:
            raise ValueError("invalid lifecycle edge")
        used.add(step.execution_id)
        state, version = step.to_state, step.committed_run_version
    return state


class PublicSourceRecord(Frozen):
    """Allowlisted ingress DTO; private adapter/sanitizer owns raw-to-public mapping."""
    source_id: UUID  # generated opaque public identity; never raw source key
    project_id: UUID | None = None
    evidence_id: UUID
    category: Literal["hourly_labor", "lump_sum_labor", "product", "outsourced_labor", "integration_material"]
    amount: Decimal | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    unit: Literal["hour", "each", "source_currency"] | None = None
    occurred_at: datetime | None = None
    original_date: date | None = None
    date_precision: Literal["source_timestamp", "source_date_assigned", "unknown"]

    @field_validator("amount", mode="before")
    @classmethod
    def no_float(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("amount must be exact decimal")
        return value

    @model_validator(mode="after")
    def public_time(self):
        if self.occurred_at is not None:
            aware(self.occurred_at)
        if self.date_precision == "unknown" and (self.occurred_at is not None or self.original_date is not None):
            raise ValueError("unknown date cannot be assigned")
        if self.date_precision == "source_date_assigned" and (self.occurred_at is None or self.original_date is None):
            raise ValueError("assigned time requires original date and resulting timestamp")
        if self.date_precision == "source_timestamp" and self.occurred_at is None:
            raise ValueError("source timestamp missing")
        return self
