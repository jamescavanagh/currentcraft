"""Embedding enrichment contracts: supersaturated cloud, ionizing ray, sparse condensation, shortcut candidates.

Design source: docs/pipelines/EMBEDDING_ENRICHMENT.md. Pydantic only. Rules are defined here, not physics of records.
"""

from __future__ import annotations

import hashlib
import math
from typing import Annotated, ClassVar, Literal, Optional

from pydantic import Field, NonNegativeInt, StringConstraints, model_validator

from app.application.plate.contracts import PlateRunResult
from app.application.simulation.contracts import NodeId, TensorContract
from app.application.common.contracts import _Frozen
from app.application.simulation.tensors import TensorRef, TensorSpec

SCHEMA_VERSION = "datamesh-enrichment/v1"
Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Finite = Annotated[float, Field(allow_inf_nan=False)]

ARMS = ("real-on", "real-off", "null-on", "null-off")
PHASE_BINS = 12
ORDERS = ("cond-off", "cond-noact", "cond-first", "act-first", "act-only", "quiet")
ANOMALOUS = frozenset({"cond-off", "cond-noact", "cond-first"})
SPLICES = ("cross_up", "cross_down", "apex_top", "apex_bottom")
MAX_RECORDS = 3000

EMBEDDINGS_SPEC = TensorSpec(name="enrichment.embeddings", dims=("node", "dim"), shape=("N", "D"), dtype="float64",
                             description="Frozen projected embedding rows, in ids order.")
LABELS_SPEC = TensorSpec(name="enrichment.labels", dims=("node",), shape=("N",), dtype="int64", min_value=-1,
                         description="Caller cluster labels; -1 = unclustered.")
SPARSE_SPEC = TensorSpec(name="enrichment.sparse_code", dims=("arm", "node", "phase_bin"), shape=(4, "N", PHASE_BINS),
                         dtype="int32", min_value=0, description="Nucleations per record per 30 degree orbit-phase bin, arms in ARMS order.")
NUCLEATIONS_SPEC = TensorSpec(name="enrichment.nucleations", dims=("arm", "node"), shape=(4, "N"), dtype="int32", min_value=0,
                              description="Total nucleations per record per arm.")
FREE_SPEC = TensorSpec(name="enrichment.ion_free", dims=("arm", "node"), shape=(4, "N"), dtype="int32", min_value=0,
                       description="Nucleations that needed no ions (S >= S_c) per record per arm.")


class SlabFrame(_Frozen):
    """Frozen slab frame in embedding coordinates. Never refit per run."""

    origin: tuple[Finite, ...] = Field(min_length=1, max_length=4096, description="Plane origin, D values.")
    normal: tuple[Finite, ...] = Field(min_length=1, max_length=4096, description="Plane normal, D values; normalised by the adapter.")
    provenance: Optional[str] = Field(default=None, max_length=300, description="How the frame was chosen (e.g. seed plane, global PC).")

    @model_validator(mode="after")
    def _rules(self):
        if len(self.origin) != len(self.normal):
            raise ValueError("origin and normal must have the same dimension")
        if math.sqrt(sum(x * x for x in self.normal)) < 1e-12:
            raise ValueError("normal must be nonzero")
        return self


class ChamberParams(_Frozen):
    """Chamber rule parameters (defaults match the Condensation Chamber v8)."""

    S0: Finite = Field(default=0.82, ge=0, le=2, description="Base supersaturation.")
    eps: Finite = Field(default=0.12, ge=0, le=1, description="Expansion term from ray speed |Z dot| / Z dot_ref.")
    kappa: Finite = Field(default=0.10, ge=0, le=1, description="Out-of-slab vapour coupling; needs no ions.")
    Sc: Finite = Field(default=1.0, gt=0, le=3, description="Condensation threshold.")
    lam: Finite = Field(default=0.30, ge=0, le=3, description="Barrier lowering per unit ion load (lambda).")
    alpha: Finite = Field(default=1.5, ge=0, le=20, description="Ion deposit rate per unit coupling.")
    tau_ion: Finite = Field(default=1.4, gt=0, le=100, description="Ion decay time.")
    tau_drop: Finite = Field(default=0.5, gt=0, le=100, description="Droplet evaporation time.")
    act_threshold: Finite = Field(default=0.18, gt=0, le=10, description="Mean slab ion load I* that counts as activation.")
    width_fraction: Finite = Field(default=0.08, gt=0, le=1, description="Slab half-width w as a fraction of h_q.")
    reach_fraction: Finite = Field(default=0.20, gt=0, le=2, description="Reach band beyond the slab as a fraction of h_q.")
    gain: Finite = Field(default=1.0, ge=1, le=1000, description="Multiplies P equally in every arm.")
    k: int = Field(default=10, ge=2, le=64, description="kNN neighbours.")


class ShortcutCriteria(_Frozen):
    """When co-condensing records count as a shortcut the dense gradient field would not allow."""

    min_nucleations: int = Field(default=3, ge=1, description="Each record needs at least this many nucleations.")
    min_concentration: Finite = Field(default=0.5, gt=0, le=1, description="Share of a record's nucleations in its dominant bin.")
    min_co_passes: int = Field(default=3, ge=1, description="Passes in which both records condensed.")
    min_hops: int = Field(default=4, ge=2, description="kNN hops that make a same-cluster pair unreachable by the gradient.")
    max_reported: int = Field(default=500, ge=1, le=10000, description="Top candidates reported per arm; totals are always exact.")


class EnrichmentRequest(_Frozen):
    """Enrich a frozen embedding with a sparse condensation code driven by a plate run's object body."""

    schema_version: Literal["datamesh-enrichment/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    enrichment_id: Ident = Field(description="Run id.")
    ids: tuple[NodeId, ...] = Field(min_length=24, max_length=MAX_RECORDS, description="Record ids, rows of embeddings.")
    embeddings: TensorRef = Field(description="N x D EMBEDDINGS_SPEC rows from a frozen projection.")
    labels_real: Optional[TensorRef] = Field(default=None, description="Cluster labels for the real embedding (LABELS_SPEC).")
    labels_null: Optional[TensorRef] = Field(default=None, description="Cluster labels for the shuffled embedding; required with labels_real.")
    slab: SlabFrame = Field(description="Frozen slab frame.")
    plate_run: PlateRunResult = Field(description="Plate run whose object body is the ray (zeta, zeta_dot, times, crossings).")
    params: ChamberParams = Field(default_factory=ChamberParams, description="Chamber rules.")
    criteria: ShortcutCriteria = Field(default_factory=ShortcutCriteria, description="Shortcut criteria.")
    null_mode: Literal["axis_shuffle", "height_preserving"] = Field(default="axis_shuffle", description="axis_shuffle: permute each axis (chamber parity). height_preserving: keep every record's slab height, shuffle in-plane positions; tests whether shortcuts beat same-height coincidence.")
    salt: NonNegativeInt = Field(default=7101, description="Shuffle salt (NumPy generator; not interchangeable with the JS chamber's salts).")
    path_sources: int = Field(default=256, ge=8, le=4096, description="BFS sources sampled for mean path length.")
    embedding_source: Optional[str] = Field(default=None, max_length=300, description="Model, space, version and projection provenance.")

    @model_validator(mode="after")
    def _rules(self):
        if self.embeddings.spec != EMBEDDINGS_SPEC:
            raise ValueError("embeddings must use EMBEDDINGS_SPEC")
        n, d = self.embeddings.shape
        if n != len(self.ids) or len(set(self.ids)) != n:
            raise ValueError("ids must be unique and match embedding rows")
        if d != len(self.slab.normal):
            raise ValueError("slab dimension must match embedding dimension")
        if (self.labels_real is None) != (self.labels_null is None):
            raise ValueError("supply labels for both arms or neither, so arms are judged alike")
        for ref in (self.labels_real, self.labels_null):
            if ref is not None and (ref.spec != LABELS_SPEC or ref.shape != (n,)):
                raise ValueError("labels must use LABELS_SPEC with one entry per record")
        if self.params.k >= n:
            raise ValueError("k must be smaller than the number of records")
        if len(self.plate_run.feature_names) < 7 or self.plate_run.status != "ok":
            raise ValueError("plate run must be a complete ok run")
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class PassRecord(_Frozen):
    """One closed pass of the ray in one arm."""

    arm: Literal["real-on", "real-off", "null-on", "null-off"] = Field(description="Arm.")
    index: NonNegativeInt = Field(description="Pass number (shared across arms).")
    t0: Finite = Field(description="Pass start time.")
    t1: Finite = Field(description="Pass end time.")
    closed_by: Literal["cross_up", "cross_down", "apex_top", "apex_bottom"] = Field(description="Splice that closed the pass.")
    order: Literal["cond-off", "cond-noact", "cond-first", "act-first", "act-only", "quiet"] = Field(description="Order class.")
    anomalous: bool = Field(description="Condensation without activation having come first.")
    droplets: NonNegativeInt = Field(description="Nucleations in the pass.")
    ion_free: NonNegativeInt = Field(description="Of those, nucleations that needed no ions.")
    t_activation: Optional[Finite] = Field(default=None, description="First time mean slab ion load reached I*.")
    t_condensation: Optional[Finite] = Field(default=None, description="First nucleation time.")
    p_peak: Finite = Field(ge=0, description="Peak post-condensation P (after gain).")
    min_margin: Optional[Finite] = Field(default=None, description="Smallest barrier minus supersaturation seen in the slab; negative means condensation.")


class ShortcutCandidate(_Frozen):
    """A pair the sparse code links but the dense kNN gradient keeps apart. A candidate for HIL labeling only."""

    arm: Literal["real-on", "real-off", "null-on", "null-off"] = Field(description="Arm the pair was found in.")
    a: NodeId = Field(description="First record id.")
    b: NodeId = Field(description="Second record id.")
    co_passes: NonNegativeInt = Field(description="Passes in which both condensed.")
    hops: int = Field(ge=0, description="kNN hops between them; 99 = not connected.")
    cross_cluster: bool = Field(description="Different cluster labels.")
    phase_bin: int = Field(ge=0, lt=PHASE_BINS, description="Shared dominant 30 degree phase bin.")
    score: Finite = Field(ge=0, description="co_passes x min(hops, 12).")
    status: Literal["candidate"] = Field(default="candidate", description="Never a relation until a human labels it.")


class SmallWorldStats(_Frozen):
    """Clustering and path length of the kNN graph, without and with the arm's shortcut candidates."""

    clustering: Finite = Field(ge=0, le=1, description="Mean local clustering coefficient, kNN graph.")
    path_length: Optional[Finite] = Field(description="Mean shortest path over reachable sampled pairs, kNN graph.")
    unreachable_fraction: Finite = Field(ge=0, le=1, description="Sampled pairs with no path, kNN graph.")
    efficiency: Finite = Field(ge=0, le=1, description="Global efficiency: mean 1/d over sampled pairs, 0 when unreachable; robust to disconnection.")
    clustering_with_shortcuts: Finite = Field(ge=0, le=1, description="Same, shortcuts added.")
    path_length_with_shortcuts: Optional[Finite] = Field(description="Same, shortcuts added.")
    unreachable_fraction_with_shortcuts: Finite = Field(ge=0, le=1, description="Same, shortcuts added.")
    efficiency_with_shortcuts: Finite = Field(ge=0, le=1, description="Same, shortcuts added. Compare efficiency, not path length, when reachability changes.")


class ArmStats(_Frozen):
    """Per-arm summary of passes, droplets, sparsity, shortcuts and graph readout."""

    arm: Literal["real-on", "real-off", "null-on", "null-off"] = Field(description="Arm.")
    passes: NonNegativeInt = Field(description="Closed passes.")
    anomalous_passes: NonNegativeInt = Field(description="Passes that condensed without activation first.")
    droplets: NonNegativeInt = Field(description="Total nucleations.")
    ion_free: NonNegativeInt = Field(description="Nucleations that needed no ions.")
    sparsity: Finite = Field(ge=0, le=1, description="Fraction of zero entries in this arm's sparse code.")
    shortcut_count: NonNegativeInt = Field(description="Exact number of candidates in this arm.")
    small_world: SmallWorldStats = Field(description="Graph readout.")


class EnrichmentResult(TensorContract):
    """Sparse condensation code, passes, shortcut candidates and graph readouts for four lockstep arms."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {"sparse_code": SPARSE_SPEC, "nucleations": NUCLEATIONS_SPEC, "ion_free_counts": FREE_SPEC}
    PRODUCED_BY: ClassVar[str] = "EmbeddingEnrichmentPort"

    schema_version: Literal["datamesh-enrichment/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    enrichment_id: Ident = Field(description="Run id.")
    request_digest: Digest = Field(description="Digest of the complete request.")
    embeddings_sha256: Digest = Field(description="Input embedding digest.")
    plate_request_digest: Digest = Field(description="Digest of the plate run that drove the ray.")
    epistemic_status: Literal["simulated"] = Field(default="simulated", description="Defined rules on model state; never evidence.")
    arms: tuple[str, ...] = Field(default=ARMS, description="Axis 'arm' order.")
    ids: tuple[NodeId, ...] = Field(description="Axis 'node' order.")
    h_scale: Finite = Field(gt=0, description="h_q: 95th percentile of |h| in the real arm.")
    passes: tuple[PassRecord, ...] = Field(description="Closed passes, all arms.")
    shortcuts: tuple[ShortcutCandidate, ...] = Field(description="Top candidates per arm, by score.")
    arm_stats: tuple[ArmStats, ...] = Field(description="Per-arm summaries, ARMS order.")
    null_mode: Literal["axis_shuffle", "height_preserving"] = Field(description="Null used for the null arms.")
    shortcut_excess_on: int = Field(description="real-on minus null-on candidate count; one salt is a description, not a test.")
    shortcut_excess_off: int = Field(description="real-off minus null-off candidate count.")
    sparse_code: TensorRef = Field(description="Ref to 4 x N x 12 phase counts.")
    nucleations: TensorRef = Field(description="Ref to 4 x N totals.")
    ion_free_counts: TensorRef = Field(description="Ref to 4 x N ion-free totals.")

    def size_seed(self):
        return {"N": len(self.ids)}


CONTRACTS = (SlabFrame, ChamberParams, ShortcutCriteria, EnrichmentRequest, PassRecord, ShortcutCandidate,
             SmallWorldStats, ArmStats, EnrichmentResult)
TENSOR_CONTRACTS = (EnrichmentResult,)
INPUT_TENSORS = {"embeddings": EMBEDDINGS_SPEC, "labels": LABELS_SPEC}
