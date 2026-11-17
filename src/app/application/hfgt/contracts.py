"""HFGT capability graph contracts (datamesh-hfgt/v1). Pydantic only; no arrays.

Design source: docs/pipelines/HFGT_CAPABILITY_GRAPH.md. Every validator below traces to a rule on that page.
Reads process-first records as hetero-functional graph theory (Farid, Thompson & Schoonenberg, Sci. Rep. 12:18805,
2022): resources R, buffers B_S, operands L, processes P, capabilities E_S, the system concept A_S = J_S minus K_S,
the incidence matrices M-/M+ and the feasible-sequence matrix A_rho = M+^T M-.

A capability graph is a structural reading for a person. Readiness is never a release.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, ClassVar, Literal, Optional

from pydantic import Field, NonNegativeInt, StringConstraints, field_validator, model_validator

from app.application.common.contracts import _Frozen
from app.application.process.contracts import ProcessExecution
from app.application.simulation.contracts import TensorContract
from app.application.simulation.tensors import TensorRef, TensorSpec

SCHEMA_VERSION = "datamesh-hfgt/v1"
Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
ProcessId = Annotated[str, StringConstraints(min_length=1, max_length=300)]
OperandKey = Literal["kind_state", "kind"]
CapabilityClass = Literal["transform", "control", "hold", "transport"]
Readiness = Literal["reachable", "blocked: constraints", "unknown: translation gaps", "unreachable"]

NODE_FEATURES = ("fc_transform", "fc_transport", "fc_hold", "fc_control_ext", "available", "evidenced", "log1p_evidence",
                 "n_pull_operands", "n_inject_operands", "nonconsuming", "self_sequence", "terminal")
EDGE_FEATURES = ("n_witnesses", "crosses_buffer", "same_resource", "crosses_stage", "via_nonconsuming")

DEVIATIONS = (
    "who-vs-where: buffers are places and resources execute; HFGT fuses them in transformation resources M",
    "control executions map to transformation processes at their buffer (extension)",
    "reads and undecided checks are non-consuming identities: pull and inject the same operand (extension)",
    "exchange has no HFGT class yet and is reported as a gap",
)


class Buffer(_Frozen):
    """A place or container where operands sit: B_S. Never a person, never an object."""

    buffer_id: Ident = Field(description="Buffer id referenced by at_buffer / origin_buffer / destination_buffer.")
    kind: Literal["store", "work", "custody"] = Field(description="store holds, work transforms, custody marks a handover point.")
    label: Optional[str] = Field(default=None, max_length=120, description="Human-readable label.")
    evidence_ref: Optional[str] = Field(default=None, max_length=200, description="Where the buffer is evidenced.")


class CapabilityRef(_Frozen):
    """Names one capability: a resource doing a process (an element of E_S)."""

    process: ProcessId = Field(description="Translated process id, e.g. 'transform:build_rack@bench' or "
                                           "'refined:hold(rack:built):bench->room201'.")
    resource_id: Ident = Field(description="Executing resource.")

    @property
    def node_id(self) -> str:
        return f"{self.process}|{self.resource_id}"


class CapabilityConstraint(_Frozen):
    """One K_S row: a capability that exists but is not available (PTO, region, oversize load, no authority)."""

    capability: CapabilityRef = Field(description="The capability this constraint switches off.")
    reason: str = Field(min_length=1, max_length=200, description="Why it is unavailable.")
    evidence_ref: Optional[str] = Field(default=None, max_length=200, description="Where the constraint is evidenced.")
    valid_from: Optional[datetime] = Field(default=None, description="Inclusive start; None = always.")
    valid_to: Optional[datetime] = Field(default=None, description="Exclusive end; None = open-ended.")

    @model_validator(mode="after")
    def _window(self):
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self

    def active(self, as_of: Optional[datetime]) -> bool:
        if as_of is None:
            return True
        if self.valid_from and as_of < self.valid_from:
            return False
        return not (self.valid_to and as_of >= self.valid_to)


class CandidateEdge(_Frozen):
    """A proposed link (splice junction, knn neighbour). Never merged into feasible sequences."""

    source: CapabilityRef = Field(description="Proposed predecessor.")
    target: CapabilityRef = Field(description="Proposed successor.")
    score: float = Field(ge=0, le=1, description="Retrieval score. Retrieval confidence is not relation confidence.")
    origin: str = Field(min_length=1, max_length=80, description="Where the proposal came from, e.g. 'splice:junction'.")


class HfgtGraphRequest(_Frozen):
    """Build a capability graph from process records."""

    schema_version: Literal["datamesh-hfgt/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    frame_id: Ident = Field(description="Frame identity, e.g. 'wme-rack-synthetic'.")
    executions: tuple[ProcessExecution, ...] = Field(min_length=1, max_length=20000, description="Process records to read.")
    buffers: tuple[Buffer, ...] = Field(default=(), description="Declared buffers. Undeclared references become gaps.")
    constraints: tuple[CapabilityConstraint, ...] = Field(default=(), description="K_S rows.")
    as_of: Optional[datetime] = Field(default=None, description="Constraints are evaluated at this time; None = all active.")
    operand_key: OperandKey = Field(default="kind_state", description="kind_state keeps order through state changes.")
    existence_basis: Literal["observed"] = Field(default="observed", description="J_S from computed executions only.")
    constraint_mode: Literal["mask", "drop"] = Field(default="mask", description="mask keeps blocked nodes with no edges; drop removes them.")
    layer_scheme: Literal["input_operand_set", "output_operand_set"] = Field(default="input_operand_set", description="How edge types are chosen.")
    terminal_operands: tuple[str, ...] = Field(default=(), description="Operand keys that count as the end of the work, e.g. 'rack:commissioned'.")
    start_operands: tuple[str, ...] = Field(default=(), description="Operand@buffer places work starts from, e.g. 'equipment_kit:received@warehouse'. "
                                                                    "Empty = every capability with no predecessor.")
    candidates: tuple[CandidateEdge, ...] = Field(default=(), description="Proposals kept apart from edge_index.")

    @field_validator("buffers")
    @classmethod
    def _unique_buffers(cls, v):
        ids = [b.buffer_id for b in v]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate buffer id")
        return v

    @model_validator(mode="after")
    def _people_are_never_operands(self):
        resources = {b.resource_id for e in self.executions for b in e.executed_by}
        objects = {i.object_id for e in self.executions for i in e.incidence}
        both = sorted(resources & objects)
        if both:
            raise ValueError(f"resource ids cannot be object ids anywhere in the request: {both}")
        buffers = {b.buffer_id for b in self.buffers}
        if buffers & resources:
            raise ValueError(f"buffer ids cannot be resource ids: {sorted(buffers & resources)}")
        ids = [e.execution_id for e in self.executions]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate execution id")
        return self

    def digest(self) -> str:
        """SHA-256 of the canonical JSON request."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class CapabilityRecord(_Frozen):
    """One capability after translation: what it pulls from where and what it injects where."""

    process: ProcessId = Field(description="Translated process id.")
    resource_id: Ident = Field(description="Executing resource.")
    capability_class: CapabilityClass = Field(description="transform / control (P_mu) or hold / transport (refined P_gamma x P_eta).")
    pulls: tuple[tuple[str, str], ...] = Field(description="(operand, buffer) places it takes from: M- column.")
    injects: tuple[tuple[str, str], ...] = Field(description="(operand, buffer) places it puts into: M+ column.")
    evidence_count: NonNegativeInt = Field(description="Executions that evidence the capability.")
    evidenced: bool = Field(description="At least one binding names an evidence_ref (else asserted only).")
    nonconsuming: bool = Field(default=False, description="Reads or undecided checks: identity extension.")
    stages: tuple[str, ...] = Field(description="Stages where it was executed.")

    @property
    def node_id(self) -> str:
        return f"{self.process}|{self.resource_id}"


class TranslationGap(_Frozen):
    """A record that did not translate. Reported, never guessed: unknown is not 0."""

    execution_id: str = Field(description="Execution that did not translate.")
    object_id: Optional[str] = Field(default=None, description="Incidence involved, if any.")
    reason: str = Field(min_length=1, max_length=200, description="Why.")


class TranslationReport(_Frozen):
    gaps: tuple[TranslationGap, ...] = Field(default=(), description="Everything that did not translate.")
    n_executions: NonNegativeInt = Field(description="Executions read.")
    n_translated: NonNegativeInt = Field(description="Executions that produced at least one capability.")
    deviations: tuple[str, ...] = Field(default=DEVIATIONS, description="Documented departures from the paper.")

    @property
    def coverage(self) -> float:
        return self.n_translated / self.n_executions if self.n_executions else 0.0


class HfgtTranslation(_Frozen):
    """Output of translate(): semantic records only, no arrays."""

    capabilities: tuple[CapabilityRecord, ...] = Field(description="E_S in canonical order (sorted node ids).")
    report: TranslationReport = Field(description="Gaps and coverage.")


def _spec(**kw) -> TensorSpec:
    return TensorSpec(**kw)


class CapabilityGraphSample(TensorContract):
    """Output of HfgtGraphPort.build(): PyTorch Geometric conventions, held as refs."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {
        "x": _spec(name="hfgt.x", dims=("node", "feature"), shape=("N", "F"), dtype="float32", layout="NF",
                   description="Capability features, order given by node_feature_names."),
        "edge_index": _spec(name="hfgt.edge_index", dims=("pair", "edge"), shape=(2, "E"), dtype="int64", layout="COO",
                            min_value=0, description="Feasible sequences: row 0 predecessor, row 1 successor; indices into node_ids."),
        "edge_attr": _spec(name="hfgt.edge_attr", dims=("edge", "edge_feature"), shape=("E", "D"), dtype="float32",
                           description="Edge features, order given by edge_feature_names."),
        "edge_type": _spec(name="hfgt.edge_type", dims=("edge",), shape=("E",), dtype="int64", min_value=0,
                           description="Layer of the edge's target (index into layer_ids): relation type for a relational GNN."),
        "candidate_edge_index": _spec(name="hfgt.candidate_edge_index", dims=("pair", "candidate"), shape=(2, "C"), dtype="int64",
                                      layout="COO", min_value=0, description="Proposed links, never feasible sequences."),
    }
    PRODUCED_BY: ClassVar[str] = "HfgtGraphPort"

    schema_version: Literal["datamesh-hfgt/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    frame_id: Ident = Field(description="Frame identity.")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of the request.")
    node_ids: tuple[str, ...] = Field(description="'process|resource' per x row.")
    node_feature_names: tuple[str, ...] = Field(default=NODE_FEATURES, description="Column order of x.")
    edge_feature_names: tuple[str, ...] = Field(default=EDGE_FEATURES, description="Column order of edge_attr.")
    layer_ids: tuple[str, ...] = Field(description="Edge type vocabulary: operand sets joined with ' + '.")
    witnesses: tuple[tuple[int, str, str], ...] = Field(default=(), description="(edge index, operand, buffer) for every edge.")
    dof_s: NonNegativeInt = Field(description="Available capabilities: sum of A_S.")
    dof_rho: NonNegativeInt = Field(description="Feasible sequences after constraints: sum of A_rho.")
    readiness: Readiness = Field(description="Structural reading for a person, never a release.")
    dead_ends: tuple[str, ...] = Field(default=(), description="Available capabilities that feed nothing and are not terminal.")
    report: TranslationReport = Field(description="Translation gaps and coverage.")
    constraint_mode: Literal["mask", "drop"] = Field(description="How K_S was applied.")
    x: TensorRef = Field(description="Ref to node features.")
    edge_index: TensorRef = Field(description="Ref to COO edges.")
    edge_attr: TensorRef = Field(description="Ref to edge features.")
    edge_type: TensorRef = Field(description="Ref to edge types.")
    candidate_edge_index: Optional[TensorRef] = Field(default=None, description="Ref to proposed links, if any.")

    def size_seed(self):
        return {"N": len(self.node_ids), "F": len(self.node_feature_names), "D": len(self.edge_feature_names),
                "E": self.dof_rho}

    @model_validator(mode="after")
    def _consistent(self):
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("duplicate node id")
        if self.dof_s > len(self.node_ids):
            raise ValueError("dof_s cannot exceed the node count")
        return self


TENSOR_CONTRACTS = (CapabilityGraphSample,)
CONTRACTS = (Buffer, CapabilityRef, CapabilityConstraint, CandidateEdge, HfgtGraphRequest, CapabilityRecord, TranslationGap,
             TranslationReport, HfgtTranslation, CapabilityGraphSample)
