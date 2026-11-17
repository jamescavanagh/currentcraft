"""Simulation contracts: the documented boundary between use cases and numeric adapters.

Every tensor-bearing result is a ``TensorContract``. Its ``TENSORS`` registry is the single
source for (a) validation of each ``TensorRef`` field, (b) cross-tensor symbol binding and
(c) the generated docs in ``docs/contracts/``. Change a spec here and the docs check fails
until ``scripts/gen_contract_docs.py`` is re-run.

Results are labelled ``embedding_geometry``: they describe the geometry of embedded records
as a procedural vortex field. They are not CFD and not operational process forecasts.
"""

from __future__ import annotations

import hashlib
import math
from enum import Enum
from typing import Annotated, ClassVar, Literal, Optional

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, NonNegativeInt, StringConstraints, field_validator, model_validator

from .tensors import TensorRef, TensorSpec, check_bindings

SCHEMA_VERSION = "datamesh-sim/v2"
LEGACY_SCHEMA_VERSIONS = ("datamesh-sim/v1",)


def _read_legacy_version(v):
    """v2 renamed the Jacobian eigenvalue key to mu_min_abs (lambda means inflow only; pre-0.9.8 key still read).
    v1 payloads still read; they are upgraded on input and always written back as v2."""
    return SCHEMA_VERSION if v in LEGACY_SCHEMA_VERSIONS else v


SchemaVersion = Annotated[Literal["datamesh-sim/v2"], BeforeValidator(_read_legacy_version)]
ResultKind = Literal["embedding_geometry"]
NodeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
FrameId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
Finite = Annotated[float, Field(allow_inf_nan=False)]

FIELD_CHANNELS = ("u", "v", "vorticity", "divergence", "speed")
NODE_FEATURES = ("x", "y", "strength", "abs_strength", "sign", "role_resource", "role_process", "role_operand",
                 "role_unassigned", "speed", "divergence", "nearest_saddle_distance", "basin_share")
EDGE_FEATURES = ("coupling", "abs_coupling", "distance", "same_sign")


from app.application.common.contracts import _Frozen  # noqa: E402,F401  (re-exported for one release; moved in 0.9.9)


# ----------------------------------------------------------------------------- inputs

class NodeRole(str, Enum):
    """Resource-Process-Operand working triad (see the domain prototype's Body). Mapping is not yet approved."""

    RESOURCE = "resource"
    PROCESS = "process"
    OPERAND = "operand"
    UNASSIGNED = "unassigned"


class InteractionNode(_Frozen):
    """One record as a point vortex: position from salted embedding PCs, strength from density, sign from PC3."""

    id: NodeId = Field(description="Stable node id (record id or vortex index).")
    role: NodeRole = Field(default=NodeRole.UNASSIGNED, description="Resource/Process/Operand role, if known.")
    x: Finite = Field(ge=-100, le=100, description="Field-plane x (model units).")
    y: Finite = Field(ge=-100, le=100, description="Field-plane y (model units).")
    strength: Finite = Field(ge=-10, le=10, description="Signed circulation; sign is spin direction.")
    label: Optional[str] = Field(default=None, max_length=300, description="Human label, e.g. the record text.")
    source_ref: Optional[str] = Field(default=None, max_length=200, description="Provenance: record id/version or citation.")


class InflowSweep(_Frozen):
    """Inflow values to evaluate, strictly increasing in [0, 1]."""

    values: tuple[Finite, ...] = Field(min_length=1, max_length=512, description="Inflow per slice.")

    @field_validator("values")
    @classmethod
    def _increasing(cls, v):
        if any(not 0 <= x <= 1 for x in v):
            raise ValueError("inflow values must be in [0, 1]")
        if any(b <= a for a, b in zip(v, v[1:])):
            raise ValueError("inflow values must be strictly increasing")
        return v

    @classmethod
    def grid(cls, start: float, stop: float, step: float) -> "InflowSweep":
        """Inclusive grid, e.g. ``InflowSweep.grid(0, 0.3, 0.02)`` gives 16 slices."""
        n = int(round((stop - start) / step)) + 1
        return cls(values=tuple(round(start + i * step, 6) for i in range(n)))


class FieldGrid(_Frozen):
    """Square sampling grid on [-extent, extent]^2. Row 0 is y = +extent (image order)."""

    size: int = Field(default=32, ge=8, le=256, description="Cells per side (G).")
    extent: Finite = Field(default=2.0, gt=0, le=100, description="Half-width of the grid in model units.")


class FieldParams(_Frozen):
    """Kernel constants shared by every simulator. Defaults match the labeling bench."""

    softening: Finite = Field(default=0.02, gt=0, description="Added to r^2 to avoid singular cores.")
    scale: Finite = Field(default=6.0, gt=0, description="Overall circulation scale (divided by N).")
    seeds: int = Field(default=40, ge=8, le=200, description="Newton seed grid per side for critical points.")


class _NodeSetMixin(_Frozen):
    nodes: tuple[InteractionNode, ...] = Field(min_length=1, max_length=4096, description="Vortex nodes.")

    @field_validator("nodes")
    @classmethod
    def _unique(cls, v):
        ids = [n.id for n in v]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate node id")
        if all(n.strength == 0 for n in v):
            raise ValueError("at least one node needs nonzero strength")
        # 0.9.9: canonical order by node id, so the digest and every tensor row order are independent of input order
        return tuple(sorted(v, key=lambda n: n.id))

    def digest(self) -> str:
        """SHA-256 of the canonical JSON request: links results to exactly what was asked."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class NodeInteractionRequest(_NodeSetMixin):
    """Simulate node interactions over an inflow sweep: coupling matrix, field, critical points, collisions."""

    schema_version: SchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round (e.g. synthetic-example).")
    result_kind: ResultKind = Field(default="embedding_geometry", description="Always embedding_geometry: a demonstration over embedded records, not an operational forecast.")
    inflow: InflowSweep = Field(description="Inflow values to evaluate (one slice each).")
    grid: Optional[FieldGrid] = Field(default_factory=FieldGrid, description="None skips the field tensor.")
    params: FieldParams = Field(description="Kernel constants (softening, scale, Newton seeds).", default_factory=FieldParams)
    refine_events: int = Field(default=7, ge=0, le=20, description="Bisection steps per collision.")


class BufferRingRequest(_NodeSetMixin):
    """Advect tracers at one inflow and measure the rings they settle into around each core."""

    schema_version: SchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round (e.g. synthetic-example).")
    result_kind: ResultKind = Field(default="embedding_geometry", description="Always embedding_geometry: a demonstration over embedded records, not an operational forecast.")
    inflow: Finite = Field(gt=0, le=1, description="Inflow > 0 (at 0 nothing drains).")
    grid: FieldGrid = Field(default_factory=FieldGrid, description="One tracer per grid cell (P = G*G).")
    params: FieldParams = Field(description="Kernel constants (softening, scale, Newton seeds).", default_factory=FieldParams)
    steps: int = Field(default=700, ge=10, le=20000, description="Advection steps.")
    step_length: Finite = Field(default=0.03, gt=0, le=1, description="Max distance a tracer moves per step.")
    capture_radius: Finite = Field(default=0.25, gt=0, description="A tracer within this of a core counts as captured.")
    history_len: int = Field(default=64, ge=1, le=1024, description="Ring-buffer length T of occupancy history.")
    record_every: int = Field(default=10, ge=1, description="Record occupancy every k steps.")


class GraphSampleRequest(_NodeSetMixin):
    """Build GNN tensors (PyG-style) for the nodes at one inflow."""

    schema_version: SchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round (e.g. synthetic-example).")
    inflow: Finite = Field(description="Inflow the node features are computed at.", ge=0, le=1)
    params: FieldParams = Field(description="Kernel constants (softening, scale, Newton seeds).", default_factory=FieldParams)
    edge_rule: Literal["knn", "coupling"] = Field(default="knn", description="knn: k nearest; coupling: |k_ij| >= threshold.")
    k: int = Field(description="Neighbours per node for knn edges.", default=6, ge=1, le=64)
    coupling_threshold: Finite = Field(description="Minimum |k_ij| for coupling edges.", default=0.0, ge=0)
    rings: Optional["BufferRingResult"] = Field(default=None, description="Adds basin_share node features.")


# ----------------------------------------------------------------------------- tensor contracts

class TensorContract(_Frozen):
    """Base for results that carry tensors. Subclasses declare ``TENSORS`` and size seeds."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {}
    PRODUCED_BY: ClassVar[str] = ""

    def size_seed(self) -> dict[str, int]:
        return {}

    def tensor_refs(self) -> dict[str, Optional[TensorRef]]:
        return {name: getattr(self, name) for name in self.TENSORS}

    @model_validator(mode="after")
    def _tensors_match_registry(self):
        for name, spec in self.TENSORS.items():
            ref = getattr(self, name)
            if ref is not None and ref.spec != spec:
                raise ValueError(f"{name}: spec differs from {type(self).__name__}.TENSORS[{name!r}]")
        check_bindings(self.tensor_refs(), self.size_seed())
        return self


class PointKind(str, Enum):
    SADDLE = "saddle"
    SPIRAL_SINK = "spiral_sink"
    NODE_SINK = "node_sink"
    CENTRE = "centre"
    SOURCE = "source"


CORE_KINDS = (PointKind.SPIRAL_SINK, PointKind.NODE_SINK, PointKind.CENTRE)


class CriticalPoint(_Frozen):
    x: Finite = Field(description="Point x.")
    y: Finite = Field(description="Point y.")
    kind: PointKind = Field(description="Classification from the Jacobian.")
    det: Finite = Field(description="Jacobian determinant; < 0 is a saddle.")
    trace: Finite = Field(description="Jacobian trace (divergence at the point).")
    mu_min_abs: Optional[Finite] = Field(
        default=None,
        validation_alias=AliasChoices("mu_min_abs", "lambda_min_abs"),
        description="Smallest |eigenvalue| mu of the Jacobian (saddles only). Eigenvalues are mu so lambda only ever means "
                    "inflow. Input still accepts the pre-0.9.8 key lambda_min_abs (deprecated alias); output is mu_min_abs.",
    )
    nearest_node_id: Optional[NodeId] = Field(default=None, description="Closest node (attribution hint, not causation).")


class InflowSlice(_Frozen):
    inflow: Finite = Field(description="Inflow of this slice.")
    saddle_count: NonNegativeInt = Field(description="Saddles found.")
    core_count: NonNegativeInt = Field(description="Sinks or centres found.")
    points: tuple[CriticalPoint, ...] = Field(default=(), description="All critical points, saddles first.")

    @model_validator(mode="after")
    def _counts(self):
        s = sum(p.kind == PointKind.SADDLE for p in self.points)
        c = sum(p.kind in CORE_KINDS for p in self.points)
        if (s, c) != (self.saddle_count, self.core_count):
            raise ValueError(f"counts ({self.saddle_count}, {self.core_count}) disagree with points ({s}, {c})")
        return self


class CollisionEvent(_Frozen):
    """Saddle-count change between two slices, refined by bisection."""

    inflow: Finite = Field(description="Refined inflow of the change.")
    saddles_before: NonNegativeInt = Field(description="Count just below.")
    saddles_after: NonNegativeInt = Field(description="Count just above.")

    @model_validator(mode="after")
    def _changes(self):
        if self.saddles_before == self.saddles_after:
            raise ValueError("an event must change the saddle count")
        return self


def _spec(**kw) -> TensorSpec:
    return TensorSpec(**kw)


class NodeInteractionResult(TensorContract):
    """Output of NodeInteractionPort.simulate()."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {
        "coupling": _spec(name="coupling", dims=("node_i", "node_j"), shape=("N", "N"), dtype="float32", layout="NN",
                          unit="1/length^2", description="k_ij = g_j / (2 pi (r_ij^2 + softening)) / N * scale: rotation node j induces at node i. Diagonal 0."),
        "node_velocity": _spec(name="node_velocity", dims=("slice", "node", "component"), shape=("S", "N", 2), dtype="float32",
                               unit="length/time", description="Field velocity (u, v) at each node, per inflow slice."),
        "field": _spec(name="field", dims=("slice", "channel", "height", "width"), shape=("S", 5, "G", "G"), dtype="float32",
                       layout="SCHW", description="CNN-1 input channels " + ", ".join(FIELD_CHANNELS) + " per slice; row 0 is y = +extent."),
    }
    PRODUCED_BY: ClassVar[str] = "NodeInteractionPort"

    schema_version: SchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round (e.g. synthetic-example).")
    result_kind: ResultKind = Field(default="embedding_geometry", description="Always embedding_geometry: a demonstration over embedded records, not an operational forecast.")
    request_digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = Field(description="SHA-256 of the request that produced this result.")
    n_nodes: int = Field(description="N: number of nodes simulated.", ge=1)
    grid: Optional[FieldGrid] = Field(description="Field grid used, or None if no field was requested.")
    slices: tuple[InflowSlice, ...] = Field(description="Critical points per inflow slice, increasing inflow.", min_length=1)
    events: tuple[CollisionEvent, ...] = Field(default=(), description="Saddle-count changes refined by bisection.")
    coupling: TensorRef = Field(description="Ref to the N x N coupling matrix.")
    node_velocity: TensorRef = Field(description="Ref to field velocity at each node per slice.")
    field: Optional[TensorRef] = Field(default=None, description="Ref to the S x 5 x G x G field tensor, if a grid was requested.")

    def size_seed(self):
        seed = {"S": len(self.slices), "N": self.n_nodes}
        if self.grid is not None:
            seed["G"] = self.grid.size
        return seed

    @model_validator(mode="after")
    def _shape_rules(self):
        if (self.field is None) != (self.grid is None):
            raise ValueError("field tensor is present exactly when a grid was requested")
        inf = [s.inflow for s in self.slices]
        if any(b <= a for a, b in zip(inf, inf[1:])):
            raise ValueError("slices must be in increasing inflow order")
        return self

    @property
    def saddle_curve(self) -> tuple[int, ...]:
        return tuple(s.saddle_count for s in self.slices)


class BufferRing(_Frozen):
    """A core's settling ring: where captured tracers circle, and how full it is."""

    index: NonNegativeInt = Field(description="Ring index (matches basins values).")
    core_x: Finite = Field(description="Core x.")
    core_y: Finite = Field(description="Core y.")
    spiral: bool = Field(description="Spiral sink (oscillatory approach) vs node sink.")
    radius: Optional[Finite] = Field(default=None, ge=0, description="Median settling distance of captured tracers.")
    occupancy: NonNegativeInt = Field(description="Tracers captured at the final step.")
    share: Finite = Field(ge=0, le=1, description="occupancy / tracers.")
    nearest_node_id: Optional[NodeId] = Field(default=None, description="Closest node to the core.")


class BufferRingResult(TensorContract):
    """Output of BufferRingPort.simulate()."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {
        "basins": _spec(name="basins", dims=("height", "width"), shape=("G", "G"), dtype="int8", layout="HW",
                        min_value=-1, description="Index of the ring each grid cell's tracer ends in; -1 = not captured."),
        "occupancy_history": _spec(name="occupancy_history", dims=("ring", "step"), shape=("R", "T"), dtype="int32", min_value=0,
                                   description="Ring buffer of captured-tracer counts, oldest first; unfilled leading slots are 0."),
        "tracers_final": _spec(name="tracers_final", dims=("tracer", "component"), shape=("P", 2), dtype="float32",
                               unit="length", description="Final tracer positions (x, y); tracer p starts in grid cell p (row-major)."),
    }
    PRODUCED_BY: ClassVar[str] = "BufferRingPort"

    schema_version: SchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round (e.g. synthetic-example).")
    result_kind: ResultKind = Field(default="embedding_geometry", description="Always embedding_geometry: a demonstration over embedded records, not an operational forecast.")
    request_digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = Field(description="SHA-256 of the request that produced this result.")
    inflow: Finite = Field(description="Inflow the tracers were advected at.")
    grid: FieldGrid = Field(description="Tracer seeding grid (also the basins grid).")
    tracers: int = Field(description="P = G*G tracers, one per grid cell.", ge=1)
    history_len: int = Field(description="T: ring-buffer length of occupancy history.", ge=1)
    history_filled: NonNegativeInt = Field(description="How many history slots hold real records (<= T).")
    rings: tuple[BufferRing, ...] = Field(description="One ring per core found at this inflow.")
    unassigned_share: Finite = Field(description="Share of tracers not captured by any ring.", ge=0, le=1)
    basins: TensorRef = Field(description="Ref to the G x G basin map.")
    occupancy_history: Optional[TensorRef] = Field(default=None, description="None when there are no rings.")
    tracers_final: TensorRef = Field(description="Ref to final tracer positions.")

    def size_seed(self):
        seed = {"G": self.grid.size, "P": self.tracers, "T": self.history_len}
        if self.rings:
            seed["R"] = len(self.rings)
        return seed

    @model_validator(mode="after")
    def _conservation(self):
        if self.tracers != self.grid.size ** 2:
            raise ValueError("one tracer per grid cell: tracers must equal G*G")
        if self.history_filled > self.history_len:
            raise ValueError("history_filled exceeds history_len")
        if (self.occupancy_history is None) != (not self.rings):
            raise ValueError("occupancy_history is present exactly when rings exist")
        total = sum(r.share for r in self.rings) + self.unassigned_share
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"ring shares + unassigned must sum to 1, got {total:.6f}")
        if [r.index for r in self.rings] != list(range(len(self.rings))):
            raise ValueError("ring indices must be 0..R-1 in order")
        return self


class CnnSampleRequest(_Frozen):
    """Turn a NodeInteractionResult into a CNN-1 -> CNN-2 training sample (same layout as models/cnn_cnn)."""

    source: NodeInteractionResult = Field(description="Interaction result whose field becomes CNN input.")
    normalize: Literal["none", "per_channel_std"] = Field(default="none", description="Per-channel std scaling across slices, or none.")
    heat_sigma_px: Finite = Field(description="Heatmap Gaussian width in pixels.", default=1.0, gt=0, le=8)


class CnnSample(TensorContract):
    """Output of CnnSamplePort.build(). Targets are the exact oracle labels, not model predictions."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {
        "x": _spec(name="cnn.x", dims=("slice", "channel", "height", "width"), shape=("S", 5, "G", "G"), dtype="float32",
                   layout="SCHW", description="CNN-1 input; CNN-2 runs along slice. Channels " + ", ".join(FIELD_CHANNELS) + "."),
        "heat": _spec(name="cnn.heat", dims=("slice", "channel", "height", "width"), shape=("S", 2, "G", "G"), dtype="float32",
                      layout="SCHW", min_value=0, max_value=1, description="Gaussian heatmaps: channel 0 saddles, 1 cores."),
        "saddle_count": _spec(name="cnn.saddle_count", dims=("slice",), shape=("S",), dtype="int16", min_value=0,
                              description="Saddles per slice (CNN-2 curve target)."),
        "core_count": _spec(name="cnn.core_count", dims=("slice",), shape=("S",), dtype="int16", min_value=0,
                            description="Cores per slice."),
    }
    PRODUCED_BY: ClassVar[str] = "CnnSamplePort"

    schema_version: SchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round (e.g. synthetic-example).")
    source_digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = Field(description="request_digest of the source NodeInteractionResult.")
    inflows: tuple[Finite, ...] = Field(description="Inflow per slice (S values).", min_length=1)
    normalization: Literal["none", "per_channel_std"] = Field(description="Normalisation applied to x.")
    x: TensorRef = Field(description="Ref to CNN input.")
    heat: TensorRef = Field(description="Ref to saddle/core heatmaps.")
    saddle_count: TensorRef = Field(description="Ref to saddles per slice.")
    core_count: TensorRef = Field(description="Ref to cores per slice.")

    def size_seed(self):
        return {"S": len(self.inflows)}


class GraphSample(TensorContract):
    """Output of GraphTensorPort.build(): PyTorch Geometric conventions, held as refs."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {
        "x": _spec(name="gnn.x", dims=("node", "feature"), shape=("N", "F"), dtype="float32", layout="NF",
                   description="Node features, order given by node_feature_names."),
        "edge_index": _spec(name="gnn.edge_index", dims=("pair", "edge"), shape=(2, "E"), dtype="int64", layout="COO",
                            min_value=0, description="Directed edges (source row 0, target row 1); indices into node_ids."),
        "edge_attr": _spec(name="gnn.edge_attr", dims=("edge", "edge_feature"), shape=("E", "D"), dtype="float32",
                           description="Edge features, order given by edge_feature_names."),
    }
    PRODUCED_BY: ClassVar[str] = "GraphTensorPort"

    schema_version: SchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round (e.g. synthetic-example).")
    inflow: Finite = Field(description="Inflow the features describe.")
    edge_rule: Literal["knn", "coupling"] = Field(description="How edges were chosen.")
    node_ids: tuple[NodeId, ...] = Field(description="Node order for x rows and edge indices.", min_length=1)
    node_feature_names: tuple[str, ...] = Field(default=NODE_FEATURES, description="Column order of x (F names).")
    edge_feature_names: tuple[str, ...] = Field(default=EDGE_FEATURES, description="Column order of edge_attr (D names).")
    x: TensorRef = Field(description="Ref to node features.")
    edge_index: TensorRef = Field(description="Ref to COO edges.")
    edge_attr: TensorRef = Field(description="Ref to edge features.")

    def size_seed(self):
        return {"N": len(self.node_ids), "F": len(self.node_feature_names), "D": len(self.edge_feature_names)}

    @model_validator(mode="after")
    def _unique(self):
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("duplicate node id")
        return self


class TransformSpec(_Frozen):
    """A tensor-to-tensor transform executed by TensorTransformPort (never in application code)."""

    op: Literal["select_slices", "normalize_per_channel", "astype"] = Field(description="Transform to apply.")
    indices: tuple[NonNegativeInt, ...] = Field(default=(), description="select_slices: slice indices to keep, in order.")
    dtype: Optional[Literal["float32", "float64"]] = Field(default=None, description="astype: target float dtype.")

    @model_validator(mode="after")
    def _params(self):
        if self.op == "select_slices" and not self.indices:
            raise ValueError("select_slices needs indices")
        if self.op == "astype" and self.dtype is None:
            raise ValueError("astype needs dtype")
        return self


class FramePipelineRequest(_NodeSetMixin):
    """One call: interactions over a sweep, rings at one inflow, then CNN and GNN samples."""

    schema_version: SchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round (e.g. synthetic-example).")
    inflow: InflowSweep = Field(description="Sweep for interactions and the CNN sample.")
    ring_inflow: Finite = Field(description="Single inflow for rings and graph features.", gt=0, le=1)
    grid: FieldGrid = Field(description="Field and tracer grid.", default_factory=FieldGrid)
    params: FieldParams = Field(description="Kernel constants (softening, scale, Newton seeds).", default_factory=FieldParams)
    ring_steps: int = Field(description="Tracer advection steps.", default=700, ge=10, le=20000)
    edge_rule: Literal["knn", "coupling"] = Field(default="knn", description="GNN edge rule.")
    k: int = Field(description="Neighbours per node for knn edges.", default=6, ge=1, le=64)


class FramePipelineResult(_Frozen):
    frame_id: FrameId = Field(description="Frame identity shared by every stage.")
    interactions: NodeInteractionResult = Field(description="Stage 1 result.")
    rings: BufferRingResult = Field(description="Stage 2 result.")
    cnn: CnnSample = Field(description="Stage 3 sample (CNN-1 -> CNN-2 input).")
    graph: GraphSample = Field(description="Stage 4 sample (GNN input).")

    @model_validator(mode="after")
    def _same_frame(self):
        ids = {self.interactions.frame_id, self.rings.frame_id, self.cnn.frame_id, self.graph.frame_id}
        if ids != {self.frame_id}:
            raise ValueError("all stages must share one frame_id")
        if len(self.graph.node_ids) != self.interactions.n_nodes:
            raise ValueError("graph and interactions disagree on N")
        return self


GraphSampleRequest.model_rebuild()

CONTRACTS = (InteractionNode, InflowSweep, FieldGrid, FieldParams, NodeInteractionRequest, NodeInteractionResult,
             BufferRingRequest, BufferRingResult, CnnSampleRequest, CnnSample, GraphSampleRequest, GraphSample,
             TransformSpec, FramePipelineRequest, FramePipelineResult)
TENSOR_CONTRACTS = (NodeInteractionResult, BufferRingResult, CnnSample, GraphSample)
