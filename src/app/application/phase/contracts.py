"""Synthetic phase-nucleation contracts (currentcraft-phase/v1). Pydantic only; no arrays, no adapters.

Design source: docs/pipelines/PHASE_NUCLEATION.md. Every validator below traces to a rule on that page.
These records describe a synthetic, offline evaluation. None of them releases work, grants authority,
or asserts a commercial fact. A transition is a recorded state change; an acceptance decision is a
separately scoped human record; a ledger observation is supplied independently and never derived.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import Field, NonNegativeInt, PositiveInt, StringConstraints, field_validator, model_validator

from app.application.common.contracts import _Frozen

SCHEMA_VERSION = "currentcraft-phase/v1"

Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
RevisionRef = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}@[A-Za-z0-9._:-]{1,120}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[str, StringConstraints(min_length=1, max_length=80)]

PhaseState = Literal["possible", "conditional", "ready", "executing", "accepted"]
PHASE_STATES: tuple[str, ...] = ("possible", "conditional", "ready", "executing", "accepted")
TRANSIENT_STATES: tuple[str, ...] = ("possible", "conditional", "ready", "executing")
ABSORBING_STATES: tuple[str, ...] = ("accepted",)

# Allowed (prior, next) pairs. None -> possible creates a proposed phase. Returns go back to conditional or possible.
# accepted is absorbing for a fixed revision: later issues open a new revision, never a transition out of accepted.
ALLOWED_TRANSITIONS: frozenset[tuple[Optional[str], str]] = frozenset({
    (None, "possible"),
    ("possible", "conditional"),
    ("conditional", "ready"), ("conditional", "possible"),
    ("ready", "executing"), ("ready", "conditional"),
    ("executing", "accepted"), ("executing", "conditional"),
})
# Entering these states on the governance trace requires a scoped decision reference.
DECISION_STATES: tuple[str, ...] = ("executing", "accepted")

EvidenceValidity = Literal["valid", "stale", "failed", "unknown", "inaccessible"]


def _aware(value: Optional[datetime], name: str) -> Optional[datetime]:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _unique(values: tuple, name: str) -> tuple:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {name}")
    return values


class PhaseRevision(_Frozen):
    """One fixed revision (``phase_id@revision_id``) of a subsystem phase. A later issue opens a new revision, never a mutation."""

    schema_version: Literal["currentcraft-phase/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    phase_id: Ident = Field(description="Opaque phase id, stable across revisions.")
    revision_id: Ident = Field(description="Opaque revision id of this phase.")
    subsystem_id: Ident = Field(description="Opaque subsystem id the phase belongs to.")
    ordinal: PositiveInt = Field(description="Position of the phase within its subsystem, starting at 1.")
    entry_profile_version: Version = Field(description="Version of this phase's published entry criteria. "
                                                        "It is fixed before the predecessor is accepted.")
    requires_accepted: tuple[RevisionRef, ...] = Field(default=(), description="Predecessor revisions that must hold a scoped "
                                                                               "acceptance before this phase can leave 'possible'.")
    nucleated_from: Optional[RevisionRef] = Field(default=None, description="Accepted revision whose decision proposed this phase. "
                                                                           "None for a first phase.")

    @property
    def ref(self) -> str:
        """``phase_id@revision_id``."""
        return f"{self.phase_id}@{self.revision_id}"

    @field_validator("requires_accepted")
    @classmethod
    def _unique_requirements(cls, v):
        return _unique(v, "predecessor revision")

    @model_validator(mode="after")
    def _no_self_reference(self):
        if self.ref in self.requires_accepted or self.nucleated_from == self.ref:
            raise ValueError("a revision cannot require or nucleate itself")
        if self.nucleated_from is not None and self.nucleated_from not in self.requires_accepted:
            raise ValueError("nucleated_from must also be listed in requires_accepted")
        return self


class PhaseReading(_Frozen):
    """A measurement or candidate offered as phase evidence, with its full envelope. Never an edge or a decision."""

    schema_version: Literal["currentcraft-phase/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    reading_id: Ident = Field(description="Opaque reading id, referenced by events and decisions.")
    phase_ref: RevisionRef = Field(description="Revision the reading is offered for.")
    kind: Literal["measurement", "candidate"] = Field(description="measurement is computed from a source; candidate is a proposal "
                                                                  "(geometry link, traced lane, ranked pair) awaiting human review.")
    source_id: Ident = Field(description="Opaque source id.")
    source_version: Version = Field(description="Source version or revision the reading was taken from.")
    mapping_digest: Digest = Field(description="SHA-256 of the mapping that translated source fields.")
    config_digest: Digest = Field(description="SHA-256 of the run configuration.")
    method: Version = Field(description="Method name and version, e.g. 'winding-det-sign/1'.")
    tolerances: tuple[tuple[str, float], ...] = Field(default=(), description="(name, non-negative tolerance) pairs used by the method.")
    coordinates: Optional[tuple[float, ...]] = Field(default=None, max_length=8, description="Sample coordinates on the synthetic plate, if any.")
    validity: EvidenceValidity = Field(description="valid, stale, failed, unknown or inaccessible. These stay distinct; none is zero.")
    run_ref: Ident = Field(description="Run that produced the reading.")
    observed_at: datetime = Field(description="Timezone-aware time the reading was taken.")
    epistemic_status: Literal["synthetic"] = Field(default="synthetic", description="Alpha scope: synthetic fixtures only.")

    @field_validator("tolerances")
    @classmethod
    def _tolerances(cls, v):
        _unique(tuple(name for name, _ in v), "tolerance name")
        if any(t < 0 for _, t in v):
            raise ValueError("tolerances must be non-negative")
        return v

    @field_validator("observed_at")
    @classmethod
    def _tz(cls, v):
        return _aware(v, "observed_at")


class PhaseTransitionEvent(_Frozen):
    """One append-only state change of a phase revision, on either the simulation or the governance trace."""

    schema_version: Literal["currentcraft-phase/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    event_id: Ident = Field(description="Opaque event id.")
    idempotency_key: Ident = Field(description="Replay key. Same key and input digest is a no-op; a changed input is a conflict.")
    phase_ref: RevisionRef = Field(description="Revision whose state changes.")
    sequence: NonNegativeInt = Field(description="Position in the revision's event chain; 0 only for the creating event.")
    prior_state: Optional[PhaseState] = Field(description="State before the event; None only for the creating event.")
    next_state: PhaseState = Field(description="State after the event.")
    input_digest: Digest = Field(description="SHA-256 of the behaviour-affecting inputs.")
    transition_policy_version: Version = Field(description="Version of the transition rules applied.")
    trace: Literal["simulation", "governance"] = Field(description="simulation records synthetic dynamics and can never carry authority; "
                                                                   "governance records the human decision chain. They are distinct traces.")
    evidence_refs: tuple[Ident, ...] = Field(default=(), description="Reading ids the transition relied on.")
    decision_ref: Optional[Ident] = Field(default=None, description="Acceptance decision id. Required on the governance trace for "
                                                                    "'executing' and 'accepted'; forbidden on the simulation trace.")
    occurred_at: datetime = Field(description="Timezone-aware event time.")

    @field_validator("evidence_refs")
    @classmethod
    def _unique_evidence(cls, v):
        return _unique(v, "evidence ref")

    @field_validator("occurred_at")
    @classmethod
    def _tz(cls, v):
        return _aware(v, "occurred_at")

    @model_validator(mode="after")
    def _rules(self):
        if (self.prior_state, self.next_state) not in ALLOWED_TRANSITIONS:
            raise ValueError(f"transition {self.prior_state} -> {self.next_state} is not allowed")
        if (self.sequence == 0) != (self.prior_state is None):
            raise ValueError("sequence 0 is reserved for the creating event, which has no prior state")
        if self.trace == "simulation" and self.decision_ref is not None:
            raise ValueError("a simulation event cannot reference a decision")
        if self.trace == "governance" and self.next_state in DECISION_STATES:
            if self.decision_ref is None:
                raise ValueError(f"entering '{self.next_state}' on the governance trace requires a decision_ref")
            if self.next_state == "accepted" and not self.evidence_refs:
                raise ValueError("a governance acceptance must cite evidence")
        return self

    def replay_against(self, prior: Optional["PhaseTransitionEvent"]) -> Literal["new", "noop", "conflict"]:
        """Classify this event against an already stored event with the same idempotency key.

        >>> from datetime import datetime, timezone
        >>> e = PhaseTransitionEvent(event_id="e1", idempotency_key="k1", phase_ref="p1@r1", sequence=0,
        ...     prior_state=None, next_state="possible", input_digest="0" * 64, transition_policy_version="1",
        ...     trace="simulation", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        >>> e.replay_against(None), e.replay_against(e)
        ('new', 'noop')
        >>> e.replay_against(e.model_copy(update={"input_digest": "1" * 64}))
        'conflict'
        """
        if prior is None:
            return "new"
        if prior.idempotency_key != self.idempotency_key:
            raise ValueError("replay comparison needs the same idempotency key")
        return "noop" if prior.input_digest == self.input_digest and prior.phase_ref == self.phase_ref else "conflict"


class AcceptanceDecision(_Frozen):
    """A scoped human decision on one exact phase revision. Simulators, models, scores and labels cannot produce one."""

    schema_version: Literal["currentcraft-phase/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    decision_id: Ident = Field(description="Opaque decision id, referenced by governance events.")
    phase_ref: RevisionRef = Field(description="Exact revision decided on.")
    outcome: Literal["accept", "hold", "return"] = Field(description="accept closes the revision; hold keeps it; return sends it back for rework.")
    scope: str = Field(min_length=1, max_length=300, description="What the decision covers and what it does not.")
    authorized_role: Ident = Field(description="Role that holds the decision right (a role, not a person's name).")
    authority_ref: Ident = Field(description="Where that authority is recorded.")
    entry_check_ref: Version = Field(description="Published entry-criteria version of the successor phase, or of integration "
                                                 "acceptance, that this revision was evaluated against: the 'governs' link.")
    evidence_refs: tuple[Ident, ...] = Field(default=(), description="Reading ids the decision relied on. Required for accept.")
    rationale: str = Field(min_length=1, max_length=2000, description="Why the decision was made.")
    conditions: tuple[str, ...] = Field(default=(), description="Conditions attached to the decision.")
    decided_at: datetime = Field(description="Timezone-aware decision time.")
    expires_at: Optional[datetime] = Field(default=None, description="Timezone-aware expiry, after decided_at; None = no expiry.")
    recorded_by: Literal["human"] = Field(default="human", description="Only a human records a decision. No other value exists.")

    @field_validator("evidence_refs")
    @classmethod
    def _unique_evidence(cls, v):
        return _unique(v, "evidence ref")

    @field_validator("conditions")
    @classmethod
    def _unique_conditions(cls, v):
        return _unique(v, "condition")

    @field_validator("decided_at", "expires_at")
    @classmethod
    def _tz(cls, v, info):
        return _aware(v, info.field_name)

    @model_validator(mode="after")
    def _rules(self):
        if self.outcome == "accept" and not self.evidence_refs:
            raise ValueError("an accept decision must cite evidence")
        if self.expires_at is not None and self.expires_at <= self.decided_at:
            raise ValueError("expires_at must be after decided_at")
        return self


class LedgerObservation(_Frozen):
    """An independently supplied commercial observation (offline fixture). No amounts, no payment logic, never derived from a phase."""

    schema_version: Literal["currentcraft-phase/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    observation_id: Ident = Field(description="Opaque observation id.")
    subject_ref: Ident = Field(description="Opaque commercial subject id, e.g. a synthetic invoice id.")
    status: Literal["invoiced", "received", "reconciled"] = Field(description="Separate observations; none implies another.")
    source_id: Ident = Field(description="Opaque id of the independent source.")
    source_revision: Version = Field(description="Revision of that source when observed.")
    observed_at: datetime = Field(description="Timezone-aware observation time.")
    related_phase_refs: tuple[RevisionRef, ...] = Field(default=(), description="Revisions the observation is filed against, for reading only.")
    epistemic_status: Literal["synthetic_fixture"] = Field(default="synthetic_fixture", description="Alpha scope: offline fixture only.")

    @field_validator("related_phase_refs")
    @classmethod
    def _unique_refs(cls, v):
        return _unique(v, "phase ref")

    @field_validator("observed_at")
    @classmethod
    def _tz(cls, v):
        return _aware(v, "observed_at")


CONTRACTS = (PhaseRevision, PhaseReading, PhaseTransitionEvent, AcceptanceDecision, LedgerObservation)
