"""Gauge contracts: operands carry measured properties (gauges) read off reduced embeddings.

The reduction treats the embedding cloud as a field. Every node gets a local 2-D frame (its
local tangent plane) and a director in that frame; every link gets a connection angle
``A_ij`` (the rotation between neighbouring frames). That connection is the discrete
vector potential reduced from the embeddings. Rotating any node's frame is a gauge
transformation: it changes ``director`` and ``edge_connection`` and leaves every gauge
invariant (``edge_link``, ``triangle_holonomy``, ``triangle_charge``, ``triangle_z2``,
``node_gauges``, loop windings) unchanged. Only invariants are measurements.

Gauges are read-only measurements (local versus global conditions of each operand). They
are not GNN inputs: the GNN takes embeddings + typed relations. Results are labelled
``embedding_geometry``: a research instrument over embedded records, not an operational
forecast. The ``supply_demand`` director is PROPOSED and untested on bench data.

>>> GaugeParams().director_mode
'principal_axis'
>>> GaugeParams(director_mode="supply_demand").charge_quantum
1.0
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Annotated, ClassVar, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt, StringConstraints, field_validator, model_validator

from app.application.simulation.contracts import FrameId, NodeId, NodeRole, TensorContract
from app.application.simulation.tensors import TensorRef, TensorSpec

SCHEMA_VERSION = "datamesh-gauge/v1"
GaugeSchemaVersion = Literal["datamesh-gauge/v1"]
ResultKind = Literal["embedding_geometry"]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
StageName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:/ -]{1,80}$")]
DirectorMode = Literal["principal_axis", "supply_demand"]
Transform = Literal["frame_rotation", "frame_flip", "global_rotation", "translation", "scale", "permutation"]
ALL_TRANSFORMS: tuple[str, ...] = ("frame_rotation", "frame_flip", "global_rotation", "translation", "scale", "permutation")

NODE_GAUGE_FEATURES = ("planarity", "anisotropy", "log_density_ratio", "supersaturated", "link_coherence",
                       "coherence_vs_global", "net_holonomy", "defect_load", "z2_defects", "degree")
NODE_GAUGE_MEANINGS = {
    "planarity": "lambda2 / lambda3 of the local patch (capped at 1e6): how well a 2-D tangent plane fits. Local.",
    "anisotropy": "lambda1 / lambda2 (capped at 1e6): how well defined the principal-axis director is. Local.",
    "log_density_ratio": "log(global median kNN spacing / local kNN spacing). > 0 denser than the cloud. Local vs global.",
    "supersaturated": "1 when exp(log_density_ratio) >= supersaturation_threshold, else 0. Local vs global.",
    "link_coherence": "Mean cos(m * link) over incident links (m = 2 axis, 1 vector): local alignment order. Local.",
    "coherence_vs_global": "link_coherence minus the cloud-wide mean link coherence. Local vs global.",
    "net_holonomy": "Sum of incident triangle holonomies (radians): local curvature of the connection.",
    "defect_load": "Sum of |charge| over incident triangles: vortex (defect) load on the operand.",
    "z2_defects": "Incident triangles whose frames cannot be oriented consistently (z2 = -1).",
    "degree": "Links kept in the connection (reliable, orientable, both ends valid).",
}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ----------------------------------------------------------------------------- inputs

class FlowSide(str, Enum):
    """Which side of a subsystem's supply/demand balance a node sits on. Used only by the proposed director."""

    SUPPLY = "supply"
    DEMAND = "demand"
    NEUTRAL = "neutral"


class GaugeNode(_Frozen):
    """One operand/resource/process record whose reduced embedding row is measured."""

    id: NodeId = Field(description="Stable node id; rows of the embeddings tensor follow request.nodes order.")
    role: NodeRole = Field(default=NodeRole.UNASSIGNED, description="Resource/Process/Operand role (simulation NodeRole).")
    flow: FlowSide = Field(default=FlowSide.NEUTRAL, description="Supply/demand side; drives the proposed supply_demand director.")
    stage: Optional[StageName] = Field(default=None, description="Process stage the record belongs to, if known.")
    label: Optional[str] = Field(default=None, max_length=300, description="Human label, e.g. record text.")
    source_ref: Optional[str] = Field(default=None, max_length=200, description="Provenance: record id/version or citation.")


class EmbeddingSpaceRef(_Frozen):
    """Where the embedding rows came from. Recorded for provenance; the reduction is not re-run here."""

    model: str = Field(min_length=1, max_length=120, description="Embedding model name.")
    version: Optional[str] = Field(default=None, max_length=80, description="Model or index version.")
    reduction: str = Field(default="none", max_length=80, description="Reduction applied upstream, e.g. pca-32 or umap-16.")
    labeling_round: Optional[PositiveInt] = Field(default=None, description="Labeling round the frame is pinned to.")
    salt: Optional[NonNegativeInt] = Field(default=None, description="Salt used for this replicate (test salt invariance, not salt value).")


class GaugeParams(_Frozen):
    """Reduction constants. Defaults are the v0.2 protocol values."""

    k: int = Field(default=12, ge=4, le=64, description="Neighbours per node for patches and links (union kNN).")
    planarity_min: Finite = Field(default=2.0, ge=1, description="Node valid only if lambda2/lambda3 >= this.")
    director_ratio_min: Finite = Field(default=1.5, ge=1, description="principal_axis: node valid only if lambda1/lambda2 >= this.")
    reliability_min: Finite = Field(default=0.5, ge=0, le=1, description="Link kept only if the smallest singular value of O_i^T O_j >= this.")
    director_mode: DirectorMode = Field(default="principal_axis", description="principal_axis (axis, mod pi) or supply_demand (vector, mod 2 pi; PROPOSED).")
    supersaturation_threshold: Finite = Field(default=1.5, gt=0, description="Local/global density ratio marking a supersaturated operand.")
    orientation_convention: Literal["net_holonomy_positive"] = Field(default="net_holonomy_positive", description="Fixes each component's frame orientation so holonomy signs are invariant.")

    @property
    def charge_quantum(self) -> float:
        """Axis directors carry half-integer defects; vector directors integer ones."""
        return 0.5 if self.director_mode == "principal_axis" else 1.0


EMBEDDINGS_SPEC = TensorSpec(name="gauge.embeddings", dims=("node", "embedding"), shape=("N", "K"), dtype="float64",
                             layout="NK", description="Reduced embedding per node; row i is request.nodes[i].")


class GaugeLoop(_Frozen):
    """A closed cycle of node ids (last connects back to first) whose winding is measured."""

    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,80}$")] = Field(description="Loop id.")
    node_ids: tuple[NodeId, ...] = Field(min_length=3, max_length=4096, description="Cycle in order; consecutive nodes must be linked.")


class GaugeRequest(_Frozen):
    """Reduce node embeddings to operand gauges and a lattice connection (discrete vector potential)."""

    schema_version: GaugeSchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round (e.g. synthetic-example).")
    result_kind: ResultKind = Field(default="embedding_geometry", description="Always embedding_geometry: research instrument, not a forecast.")
    space: EmbeddingSpaceRef = Field(description="Provenance of the embedding rows.")
    nodes: tuple[GaugeNode, ...] = Field(min_length=5, max_length=4096, description="Nodes in embedding row order.")
    embeddings: TensorRef = Field(description="Ref to the N x K float64 reduced embeddings (gauge.embeddings).")
    params: GaugeParams = Field(default_factory=GaugeParams, description="Reduction constants.")
    loops: tuple[GaugeLoop, ...] = Field(default=(), max_length=256, description="Cycles to measure windings around.")

    @field_validator("nodes")
    @classmethod
    def _unique(cls, v):
        ids = [n.id for n in v]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate node id")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        if self.embeddings.spec != EMBEDDINGS_SPEC:
            raise ValueError("embeddings must use EMBEDDINGS_SPEC (gauge.embeddings, N x K float64)")
        n, kdim = self.embeddings.shape
        if n != len(self.nodes):
            raise ValueError(f"embeddings has {n} rows but {len(self.nodes)} nodes")
        if kdim < 3:
            raise ValueError("need at least 3 embedding dimensions to test planarity")
        if self.params.k >= n:
            raise ValueError(f"k = {self.params.k} must be < number of nodes ({n})")
        ids = {x.id for x in self.nodes}
        for loop in self.loops:
            unknown = [i for i in loop.node_ids if i not in ids]
            if unknown:
                raise ValueError(f"loop {loop.id}: unknown node ids {unknown[:3]}")
        if self.params.director_mode == "supply_demand":
            sides = {x.flow for x in self.nodes}
            if not {FlowSide.SUPPLY, FlowSide.DEMAND} <= sides:
                raise ValueError("supply_demand director needs at least one supply and one demand node")
        return self

    def digest(self) -> str:
        """SHA-256 of the canonical JSON request (embedding bytes enter via the ref's sha256)."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


# ----------------------------------------------------------------------------- results

class LoopWinding(_Frozen):
    """Winding of the director around one requested loop. Gauge invariant; quantized when complete."""

    loop_id: str = Field(description="GaugeLoop.id.")
    complete: bool = Field(description="True when every consecutive pair is a kept connection link.")
    missing_links: NonNegativeInt = Field(description="Consecutive pairs that are not kept links.")
    winding: Optional[Finite] = Field(default=None, description="(sum of links - sum of connection) / 2 pi; None if incomplete.")
    quantized: Optional[Finite] = Field(default=None, description="winding rounded to the charge quantum.")
    holonomy_deg: Optional[Finite] = Field(default=None, description="Wrapped loop holonomy (degrees): curvature enclosed.")


def _spec(**kw) -> TensorSpec:
    return TensorSpec(**kw)


class GaugeResult(TensorContract):
    """Output of GaugeReductionPort.reduce(): operand gauges plus the lattice connection and its invariants."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {
        "node_gauges": _spec(name="gauge.node_gauges", dims=("node", "feature"), shape=("N", "F"), dtype="float64", layout="NF",
                             description="Gauge-invariant operand properties, order given by node_feature_names (local and local-vs-global)."),
        "node_mask": _spec(name="gauge.node_mask", dims=("node",), shape=("N",), dtype="bool",
                           description="True where the patch is planar and the director is defined."),
        "director": _spec(name="gauge.director", dims=("node",), shape=("N",), dtype="float64", unit="rad", min_value=-3.1416, max_value=3.1416,
                          description="GAUGE-DEPENDENT director angle in the node's own frame (0 where masked). Never a measurement."),
        "edge_index": _spec(name="gauge.edge_index", dims=("pair", "edge"), shape=(2, "E"), dtype="int64", layout="COO", min_value=0,
                            description="Kept links, row 0 = lower node id, row 1 = higher node id; indices into node_ids."),
        "edge_connection": _spec(name="gauge.edge_connection", dims=("edge",), shape=("E",), dtype="float64", unit="rad", min_value=-3.1416, max_value=3.1416,
                                 description="GAUGE-DEPENDENT connection A_ij (rotation from frame j to frame i): the discrete vector potential."),
        "edge_link": _spec(name="gauge.edge_link", dims=("edge",), shape=("E",), dtype="float64", unit="rad", min_value=-3.1416, max_value=3.1416,
                           description="Covariant director difference phi_j + A_ij - phi_i (wrapped mod pi or 2 pi). Gauge invariant."),
        "edge_reliability": _spec(name="gauge.edge_reliability", dims=("edge",), shape=("E",), dtype="float64", min_value=0, max_value=1.000001,
                                  description="Smallest singular value of O_i^T O_j: how parallel the two tangent planes are."),
        "triangles": _spec(name="gauge.triangles", dims=("corner", "triangle"), shape=(3, "T"), dtype="int64", min_value=0,
                           description="Triangles of reliable links, corners in ascending node-id order (fixes the cyclic sense)."),
        "triangle_holonomy": _spec(name="gauge.triangle_holonomy", dims=("triangle",), shape=("T",), dtype="float64", unit="rad", finite=False,
                                   description="Wrapped A_ij + A_jl + A_li: curvature (field strength) through the triangle. NaN when an edge is not orientable."),
        "triangle_charge": _spec(name="gauge.triangle_charge", dims=("triangle",), shape=("T",), dtype="float64", finite=False,
                                 description="Defect charge (sum of links - holonomy) / 2 pi, quantized: a vortex in the director. NaN when not orientable."),
        "triangle_z2": _spec(name="gauge.triangle_z2", dims=("triangle",), shape=("T",), dtype="int8", min_value=-1, max_value=1,
                             description="Product of frame-orientation signs around the triangle: -1 marks a non-orientable (Mobius-like) loop."),
    }
    PRODUCED_BY: ClassVar[str] = "GaugeReductionPort"
    GAUGE_DEPENDENT: ClassVar[tuple[str, ...]] = ("director", "edge_connection")

    schema_version: GaugeSchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round.")
    result_kind: ResultKind = Field(default="embedding_geometry", description="Always embedding_geometry: research instrument, not a forecast.")
    request_digest: Digest = Field(description="SHA-256 of the request that produced this result.")
    embeddings_sha256: Digest = Field(description="SHA-256 of the embeddings tensor that was reduced.")
    director_mode: DirectorMode = Field(description="Director used.")
    charge_quantum: Literal[0.5, 1.0] = Field(description="0.5 for axis directors, 1.0 for vector directors.")
    node_ids: tuple[NodeId, ...] = Field(min_length=1, description="Row order of every node tensor.")
    node_feature_names: tuple[str, ...] = Field(default=NODE_GAUGE_FEATURES, description="Column order of node_gauges.")
    n_valid: NonNegativeInt = Field(description="Nodes with node_mask True.")
    n_links: NonNegativeInt = Field(description="E: kept links.")
    n_triangles: NonNegativeInt = Field(description="T: triangles of reliable links.")
    orientation_conflicts: NonNegativeInt = Field(description="Reliable links dropped because frames could not be oriented consistently.")
    global_link_coherence: Optional[Finite] = Field(default=None, description="Cloud-wide mean link coherence (None without links).")
    net_charge: Finite = Field(default=0.0, description="Sum of finite triangle charges.")
    loops: tuple[LoopWinding, ...] = Field(default=(), description="Windings for the requested loops, in request order.")
    node_gauges: TensorRef = Field(description="Ref to N x F operand gauges.")
    node_mask: TensorRef = Field(description="Ref to N validity mask.")
    director: TensorRef = Field(description="Ref to N gauge-dependent director angles.")
    edge_index: TensorRef = Field(description="Ref to 2 x E link index.")
    edge_connection: TensorRef = Field(description="Ref to E gauge-dependent connection angles (vector potential).")
    edge_link: TensorRef = Field(description="Ref to E gauge-invariant links.")
    edge_reliability: TensorRef = Field(description="Ref to E link reliabilities.")
    triangles: TensorRef = Field(description="Ref to 3 x T triangle corners.")
    triangle_holonomy: TensorRef = Field(description="Ref to T triangle holonomies.")
    triangle_charge: TensorRef = Field(description="Ref to T triangle defect charges.")
    triangle_z2: TensorRef = Field(description="Ref to T orientation signs.")

    def size_seed(self):
        return {"N": len(self.node_ids), "F": len(self.node_feature_names), "E": self.n_links, "T": self.n_triangles}

    @model_validator(mode="after")
    def _rules(self):
        if self.node_feature_names != NODE_GAUGE_FEATURES:
            raise ValueError("node_feature_names must equal NODE_GAUGE_FEATURES")
        if self.n_valid > len(self.node_ids):
            raise ValueError("n_valid exceeds node count")
        want = 0.5 if self.director_mode == "principal_axis" else 1.0
        if self.charge_quantum != want:
            raise ValueError(f"charge_quantum must be {want} for {self.director_mode}")
        return self

    @classmethod
    def invariant_tensors(cls) -> tuple[str, ...]:
        """Tensor names that are measurements (unchanged by any frame rotation)."""
        return tuple(n for n in cls.TENSORS if n not in cls.GAUGE_DEPENDENT)


# ----------------------------------------------------------------------------- invariance check

class GaugeCheckRequest(_Frozen):
    """Re-run a reduction under transformations that must not change any measurement."""

    request: GaugeRequest = Field(description="The reduction to check.")
    transforms: tuple[Transform, ...] = Field(default=ALL_TRANSFORMS, min_length=1, description="Transformations to apply, one run each.")
    seed: int = Field(default=0, ge=0, description="RNG seed for random rotations, flips and permutations.")
    tolerance: Finite = Field(default=1e-8, gt=0, description="Max allowed change of any invariant.")


class GaugeCheck(_Frozen):
    """One transformation's outcome."""

    transform: Transform = Field(description="Transformation applied.")
    same_structure: bool = Field(description="Same valid nodes, links and triangles (matched by node id).")
    invariant_max_dev: Finite = Field(description="Largest change of any invariant (wrapped for angles).")
    gauge_dependent_max_change: Finite = Field(description="Largest change of the connection; must be > 0 for frame_rotation.")
    passed: bool = Field(description="Structure equal, invariants within tolerance, and (frame_rotation) the gauge actually moved.")


class GaugeCheckResult(_Frozen):
    """Output of GaugeInvariancePort.check()."""

    frame_id: FrameId = Field(description="Frame checked.")
    request_digest: Digest = Field(description="Digest of the checked GaugeRequest.")
    checks: tuple[GaugeCheck, ...] = Field(min_length=1, description="One entry per transform.")
    passed: bool = Field(description="All checks passed.")

    @model_validator(mode="after")
    def _all(self):
        if self.passed != all(c.passed for c in self.checks):
            raise ValueError("passed must equal all(check.passed)")
        return self


# ----------------------------------------------------------------------------- participation null

class ParticipationEdge(_Frozen):
    """A resource node took part in a process at a stage (bipartite participation record)."""

    resource_id: NodeId = Field(description="Participating resource (person, team or tool). Never an operand: objects are things, never contributors.")
    process_id: NodeId = Field(description="Process instance.")
    stage: StageName = Field(description="Stage of the process; rewiring never crosses stages.")


class ScoredPair(_Frozen):
    """Two nodes at one stage with a local (gauge/patch) score and a global (cosine) score from the caller."""

    a: NodeId = Field(description="First node.")
    b: NodeId = Field(description="Second node.")
    stage: StageName = Field(description="Stage the pair is scored for.")
    local_score: Finite = Field(description="Local-gauge similarity (e.g. demand-only patch score).")
    global_score: Finite = Field(description="Global baseline similarity (e.g. full-space cosine).")

    @model_validator(mode="after")
    def _distinct(self):
        if self.a == self.b:
            raise ValueError("pair needs two different nodes")
        return self


def co_participation_labels(participation, pairs) -> tuple[int, ...]:
    """1 when the pair shares a process at the pair's stage. Pure Python; adapters reuse it on rewired data.

    >>> e = (ParticipationEdge(resource_id="r1", process_id="p1", stage="s"),
    ...      ParticipationEdge(resource_id="r2", process_id="p1", stage="s"))
    >>> p = (ScoredPair(a="r1", b="r2", stage="s", local_score=1, global_score=0),
    ...      ScoredPair(a="r1", b="r3", stage="s", local_score=0, global_score=0))
    >>> co_participation_labels(e, p)
    (1, 0)
    """
    sets: dict[tuple[str, str], set[str]] = {}
    for e in participation:
        sets.setdefault((e.stage, e.resource_id), set()).add(e.process_id)
    return tuple(int(bool(sets.get((p.stage, p.a), set()) & sets.get((p.stage, p.b), set()))) for p in pairs)


class StageNullRequest(_Frozen):
    """Does the local score predict co-participation beyond stage-matched chance, and beyond the global score?"""

    schema_version: GaugeSchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity, pinned to its labeling round.")
    participation: tuple[ParticipationEdge, ...] = Field(min_length=2, max_length=200000, description="Observed participation records.")
    pairs: tuple[ScoredPair, ...] = Field(min_length=2, max_length=200000, description="Scored node pairs.")
    n_rewires: int = Field(default=200, ge=10, le=5000, description="R: stage-preserving curveball rewirings for the null.")
    trades_per_node: int = Field(default=5, ge=1, le=100, description="Curveball trades per participating node per rewiring.")
    n_bootstrap: int = Field(default=500, ge=50, le=10000, description="B: stage-stratified paired bootstrap resamples of the AUC difference.")
    gain_bar: Finite = Field(default=0.05, ge=0, le=1, description="Minimum AUC_local - AUC_global to call a local gain.")
    alpha: Finite = Field(default=0.05, gt=0, lt=1, description="Significance level for the null p-value and two-sided CI.")
    seed: int = Field(default=0, ge=0, description="RNG seed.")

    @model_validator(mode="after")
    def _labels(self):
        stages = {e.stage for e in self.participation}
        bad = sorted({p.stage for p in self.pairs} - stages)
        if bad:
            raise ValueError(f"pairs reference stages without participation: {bad[:3]}")
        y = co_participation_labels(self.participation, self.pairs)
        by: dict[str, set[int]] = {}
        for p, lab in zip(self.pairs, y):
            by.setdefault(p.stage, set()).add(lab)
        if not any(v == {0, 1} for v in by.values()):
            raise ValueError("need at least one stage with both co-participating and non-co-participating pairs")
        return self

    def digest(self) -> str:
        """SHA-256 of the canonical JSON request."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class StageNullResult(TensorContract):
    """Output of ParticipationNullPort.test(). Rewiring tests signal vs chance; only the paired bootstrap tests locality."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {
        "null_auc": _spec(name="gauge.null_auc", dims=("rewire", "score"), shape=("R", 2), dtype="float64", min_value=0, max_value=1,
                          description="Stage-stratified AUC of (local, global) scores against labels from each stage-preserving rewiring."),
        "bootstrap_diff": _spec(name="gauge.bootstrap_diff", dims=("resample",), shape=("B",), dtype="float64", min_value=-1, max_value=1,
                                description="AUC_local - AUC_global on stage-stratified paired bootstrap resamples of the pairs."),
    }
    PRODUCED_BY: ClassVar[str] = "ParticipationNullPort"

    schema_version: GaugeSchemaVersion = Field(default=SCHEMA_VERSION, description="Contract version; bump on any breaking change.")
    frame_id: FrameId = Field(description="Frame identity.")
    result_kind: ResultKind = Field(default="embedding_geometry", description="Always embedding_geometry: research instrument, not a forecast.")
    request_digest: Digest = Field(description="SHA-256 of the request.")
    stages_used: tuple[str, ...] = Field(description="Stages with both labels (others cannot contribute to AUC).")
    n_pairs: NonNegativeInt = Field(description="Pairs in used stages.")
    n_positive: NonNegativeInt = Field(description="Co-participating pairs in used stages.")
    auc_local: Finite = Field(ge=0, le=1, description="Stage-stratified AUC of the local score.")
    auc_global: Finite = Field(ge=0, le=1, description="Stage-stratified AUC of the global score.")
    auc_diff: Finite = Field(ge=-1, le=1, description="auc_local - auc_global.")
    diff_ci_low: Finite = Field(ge=-1, le=1, description="Lower bootstrap bound (alpha/2).")
    diff_ci_high: Finite = Field(ge=-1, le=1, description="Upper bootstrap bound (1 - alpha/2).")
    p_local: Finite = Field(gt=0, le=1, description="(1 + #null >= observed) / (R + 1) for the local score.")
    p_global: Finite = Field(gt=0, le=1, description="Same for the global score.")
    verdict: Literal["local_beats_global", "local_signal_no_gain", "not_above_null"] = Field(
        description="not_above_null if p_local > alpha; local_beats_global if diff_ci_low > 0 and auc_diff >= gain_bar; else local_signal_no_gain.")
    null_auc: TensorRef = Field(description="Ref to R x 2 null AUCs.")
    bootstrap_diff: TensorRef = Field(description="Ref to B bootstrap differences.")


CONTRACTS = (GaugeNode, EmbeddingSpaceRef, GaugeParams, GaugeLoop, GaugeRequest, LoopWinding, GaugeResult,
             GaugeCheckRequest, GaugeCheck, GaugeCheckResult, ParticipationEdge, ScoredPair, StageNullRequest, StageNullResult)
TENSOR_CONTRACTS = (GaugeResult, StageNullResult)
INPUT_TENSORS = {"embeddings": EMBEDDINGS_SPEC}
