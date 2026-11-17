"""Process-first domain contracts. Pydantic only; no arrays.

Design source: docs/domain/PROCESS_FIRST.md. Every validator below traces to a rule on that page.
Objects are things, never people. Resources execute processes through capability bindings.
Gates are control-class executions. Simulated work never releases.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import Field, NonNegativeInt, StringConstraints, model_validator

from app.application.gauge.contracts import ParticipationEdge
from app.application.common.contracts import _Frozen

SCHEMA_VERSION = "datamesh-process/v1"

Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
StageCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,40}$")]
StateName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,60}$")]
FunctionClass = Literal["transform", "transport", "hold", "exchange", "control"]
Effect = Literal["produces", "consumes", "reads", "revises", "holds", "checks", "transfers"]
Decision = Literal["hold", "release", "reject", "return"]
EpistemicStatus = Literal["computed", "simulated", "unknown"]
AuthorityScope = Literal["release", "reject", "return", "hold", "approve_design", "transfer_custody", "commit_spend",
                         "displace_allocation"]

ALLOWED_EFFECTS: dict[str, frozenset[str]] = {
    "transform": frozenset({"produces", "consumes", "reads", "revises"}),
    "transport": frozenset({"reads", "transfers"}),
    "hold": frozenset({"reads", "holds"}),
    "exchange": frozenset({"produces", "consumes", "reads", "transfers"}),
    "control": frozenset({"reads", "checks"}),
}
DECISION_SCOPES: dict[str, frozenset[str]] = {
    "release": frozenset({"release"}), "reject": frozenset({"reject", "release"}),
    "return": frozenset({"return", "release"}), "hold": frozenset({"hold", "release"}),
}


class ProcessType(_Frozen):
    """A kind of process: what it does to objects, independent of any project instance."""

    code: Ident = Field(description="Caller vocabulary process code, e.g. 'design' or a catalogue number.")
    name: str = Field(min_length=1, max_length=120, description="Human-readable process name.")
    function_classes: tuple[FunctionClass, ...] = Field(min_length=1, description="What the process does: transform, transport, hold, exchange, control.")
    approved: bool = Field(default=False, description="True only after a process SME signs off the classification; inferred classes stay False.")

    @model_validator(mode="after")
    def _unique(self):
        if len(set(self.function_classes)) != len(self.function_classes):
            raise ValueError("function_classes must be unique")
        return self

    def allowed_effects(self) -> frozenset[str]:
        out: set[str] = set()
        for c in self.function_classes:
            out |= ALLOWED_EFFECTS[c]
        return frozenset(out)


class ObjectIncidence(_Frozen):
    """What one execution does to one object. Objects are things, never people."""

    object_id: Ident = Field(description="Persistent object id (one per asset; references to it are not new objects).")
    object_kind: Optional[str] = Field(default=None, max_length=80, description="Caller vocabulary, e.g. drawing, purchase_order, device.")
    effect: Effect = Field(description="produces=birth, consumes=death, revises/transfers/holds=state change, checks=gate, reads=no change.")
    state_before: Optional[StateName] = Field(default=None, description="Expected state before the execution, if asserted.")
    state_after: Optional[StateName] = Field(default=None, description="State after the execution, where the effect changes state.")
    origin_buffer: Optional[Ident] = Field(default=None, description="transfers only: buffer (place) the object leaves. Optional; HFGT reports a gap when missing.")
    destination_buffer: Optional[Ident] = Field(default=None, description="transfers only: buffer (place) the object arrives at. Set with origin_buffer or not at all.")

    @model_validator(mode="after")
    def _states(self):
        e = self.effect
        if e == "produces" and (self.state_before is not None or self.state_after is None):
            raise ValueError("produces: no state_before, state_after required")
        if e == "consumes" and self.state_after is not None:
            raise ValueError("consumes: the object dies, no state_after")
        if e in ("revises", "transfers", "holds") and self.state_after is None:
            raise ValueError(f"{e}: state_after required")
        if e == "reads" and self.state_after is not None:
            raise ValueError("reads: no state change")
        if (self.origin_buffer is None) != (self.destination_buffer is None):
            raise ValueError("origin_buffer and destination_buffer go together")
        if self.origin_buffer is not None and e != "transfers":
            raise ValueError("origin/destination buffers belong to transfers only")
        return self


class CapabilityBinding(_Frozen):
    """A resource executing the process. Resources (people, teams, tools) appear only here."""

    resource_id: Ident = Field(description="Resource id; never an object id.")
    resource_role: str = Field(min_length=1, max_length=80, description="Role, not a person's name, in shared artifacts.")
    evidence_ref: Optional[str] = Field(default=None, max_length=200, description="Where the capability is evidenced; None means asserted, not evidenced.")


class AuthorityRef(_Frozen):
    """A decision right attached to an execution."""

    holder_role: str = Field(min_length=1, max_length=80, description="Role holding the right.")
    scope: AuthorityScope = Field(description="What the right covers.")
    evidence_ref: Optional[str] = Field(default=None, max_length=200, description="Where the right is documented.")


class ProcessExecution(_Frozen):
    """The root record: one execution of a process type. Everything else is derived from executions."""

    schema_version: Literal["datamesh-process/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    execution_id: Ident = Field(description="Instance id, e.g. '<project>:<process-code>[:<n>]'.")
    process: ProcessType = Field(description="The process type executed.")
    stage: StageCode = Field(description="Caller stage code; the participation null never crosses stages.")
    subsystem_id: Optional[Ident] = Field(default=None, description="Subsystem the execution belongs to, if known.")
    at_buffer: Optional[Ident] = Field(default=None, description="Buffer (place) where a transform, control or hold happens. Optional; HFGT reports a gap when missing.")
    incidence: tuple[ObjectIncidence, ...] = Field(default=(), description="Objects the execution acts on, one entry per object.")
    executed_by: tuple[CapabilityBinding, ...] = Field(default=(), description="Who executed it. Empty means the executor is unknown.")
    decision: Optional[Decision] = Field(default=None, description="Gate decision; control executions only.")
    verification_evidence: tuple[Ident, ...] = Field(default=(), description="Object ids the decision relied on; each must be read or checked here.")
    authority: Optional[AuthorityRef] = Field(default=None, description="Decision right; required for release.")
    epistemic_status: EpistemicStatus = Field(default="computed", description="computed = from records; simulated work can never release.")
    occurred_at: Optional[datetime] = Field(default=None, description="Real timestamp, if recorded. Required before process claims.")
    sequence: Optional[NonNegativeInt] = Field(default=None, description="Caller ordering within ties; None means unordered.")
    source_ref: Optional[str] = Field(default=None, max_length=200, description="Provenance of the record.")

    @model_validator(mode="after")
    def _rules(self):
        ids = [i.object_id for i in self.incidence]
        if len(set(ids)) != len(ids):
            raise ValueError("one incidence per object per execution")
        resources = {b.resource_id for b in self.executed_by}
        if resources & set(ids):
            raise ValueError(f"resource ids cannot be object ids: {sorted(resources & set(ids))}")
        allowed = self.process.allowed_effects()
        bad = sorted({i.effect for i in self.incidence} - allowed)
        if bad:
            raise ValueError(f"effects {bad} not allowed for {self.process.function_classes}")
        if self.decision is None:
            if any(i.effect == "checks" and i.state_after is not None for i in self.incidence):
                raise ValueError("checks can change state only with a gate decision")
            if self.verification_evidence or self.authority is not None:
                raise ValueError("verification evidence and authority belong to a decision")
            return self
        if "control" not in self.process.function_classes:
            raise ValueError("decision requires the control function class")
        if self.decision == "release":
            if self.authority is None or self.authority.scope != "release":
                raise ValueError("release requires authority with scope 'release'")
            if not self.verification_evidence:
                raise ValueError("release requires verification evidence")
            if self.epistemic_status != "computed":
                raise ValueError("simulated or unknown work cannot release")
        elif self.authority is not None and self.authority.scope not in DECISION_SCOPES[self.decision]:
            raise ValueError(f"authority scope {self.authority.scope!r} does not cover {self.decision!r}")
        looked_at = {i.object_id for i in self.incidence if i.effect in ("reads", "checks")}
        missing = sorted(set(self.verification_evidence) - looked_at)
        if missing:
            raise ValueError(f"verification evidence must be read or checked by this execution: {missing}")
        return self

    def participation(self) -> tuple[ParticipationEdge, ...]:
        """Projection for the stage-preserving participation null. Derived, never authored."""
        return tuple(ParticipationEdge(resource_id=b.resource_id, process_id=self.execution_id, stage=self.stage)
                     for b in self.executed_by)


class ObjectEvent(_Frozen):
    """An object lifecycle event derived from an execution."""

    object_id: Ident = Field(description="Object the event is about.")
    kind: Literal["birth", "death", "state_change"] = Field(description="birth from produces, death from consumes, otherwise state change.")
    state: Optional[StateName] = Field(default=None, description="State after the event; None for deaths.")
    execution_id: Ident = Field(description="Execution that caused the event.")
    stage: StageCode = Field(description="Stage of that execution.")
    occurred_at: Optional[datetime] = Field(default=None, description="Execution timestamp, if recorded.")
    index: NonNegativeInt = Field(description="Position in the derived event chain.")


CONTRACTS = (ProcessType, ObjectIncidence, CapabilityBinding, AuthorityRef, ProcessExecution, ObjectEvent)
