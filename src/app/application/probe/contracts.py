"""Probe contracts: aperture, spin gauges, barrier brackets, lens, candidates, labels. Pydantic only.

Design source: docs/pipelines/PROBE.md. Plane/state readings are embedding geometry; vortex/field/spin readings come from
a model field of regularised vortices at slab records with explicitly supplied strengths.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import Field, NonNegativeInt, StringConstraints, model_validator

from app.application.enrichment.contracts import ARMS, EnrichmentResult
from app.application.simulation.contracts import NodeId
from app.application.common.contracts import _Frozen
from app.application.simulation.tensors import TensorRef, TensorSpec

SCHEMA_VERSION = "datamesh-probe/v1"
Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
LabelKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,60}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Vec3 = tuple[Finite, Finite, Finite]
ArmName = Literal["real-on", "real-off", "null-on", "null-off"]

POSITIONS_SPEC = TensorSpec(name="probe.positions", dims=("node", "axis"), shape=("N", 3), dtype="float64",
                            description="Frozen 3D projection of embedding rows (the fluid), in ids order.")
SLAB_COORDS_SPEC = TensorSpec(name="probe.slab_coords", dims=("node", "component"), shape=("M", 2), dtype="float64",
                              description="Plate-frame (u, v) of slab records, in slab_ids order.")


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


# ----------------------------------------------------------------------------- brackets

class Bracket(_Frozen):
    """A human-set search window [lo, hi] guarded by a Barrier Lyapunov Function."""

    lo: Finite = Field(description="Lower wall.")
    hi: Finite = Field(description="Upper wall.")
    margin: Finite = Field(default=0.02, ge=0, lt=0.5, description="Keep |e| <= (1 - margin) k_b.")
    gain: Finite = Field(default=0.0, ge=0, le=100, description="Optional centring gain k.")

    @model_validator(mode="after")
    def _order(self):
        if not self.hi > self.lo:
            raise ValueError("bracket needs hi > lo")
        return self

    @property
    def center(self) -> float:
        return 0.5 * (self.lo + self.hi)

    @property
    def half_width(self) -> float:
        return 0.5 * (self.hi - self.lo)

    def contains(self, value: float) -> bool:
        return abs(value - self.center) <= (1 - self.margin) * self.half_width + 1e-12


class BracketState(_Frozen):
    """Where a coordinate sits in its bracket."""

    value: Finite = Field(description="Current coordinate.")
    error: Finite = Field(description="e = value - centre.")
    barrier: Finite = Field(ge=0, description="V = 0.5 ln(k_b^2 / (k_b^2 - e^2)); 0 at the centre, unbounded at the walls.")
    fraction: Finite = Field(ge=0, le=1, description="|e| / k_b.")
    at_wall: bool = Field(description="True when |e| has reached (1 - margin) k_b.")


class BracketStep(_Frozen):
    """Result of filtering one human move through the barrier."""

    value: Finite = Field(description="New coordinate.")
    requested_velocity: Finite = Field(description="Human request v.")
    applied_displacement: Finite = Field(description="Displacement actually applied over dt.")
    substeps: int = Field(ge=1, description="Splitting steps for the centring gain (1 without gain).")
    state: BracketState = Field(description="State after the move.")


# ----------------------------------------------------------------------------- inputs

class RecordStrength(_Frozen):
    """Explicit vortex strength for one record, with evidence. Never inferred from projection handedness."""

    id: NodeId = Field(description="Record id.")
    strength: Finite = Field(ge=-10, le=10, description="Circulation Gamma; sign is spin direction, not good or bad.")
    source_ref: str = Field(min_length=1, max_length=200, description="Evidence for the strength.")


class RecordText(_Frozen):
    """Words shown on hover and used for contrast terms."""

    id: NodeId = Field(description="Record id.")
    title: str = Field(min_length=1, max_length=300, description="Record title; CamelCase is split into words.")
    text: Optional[str] = Field(default=None, max_length=4000, description="Optional body text.")


class ProbeCloud(_Frozen):
    """The 3D fluid: frozen projection, explicit strengths, text, existing labels, optional enrichment run."""

    cloud_id: Ident = Field(description="Cloud id.")
    ids: tuple[NodeId, ...] = Field(min_length=3, max_length=20000, description="Record ids, rows of positions.")
    positions: TensorRef = Field(description="N x 3 POSITIONS_SPEC.")
    projection_ref: str = Field(min_length=1, max_length=300, description="Frozen projection provenance (model, space, version, fit data).")
    strengths: tuple[RecordStrength, ...] = Field(default=(), description="Explicit strengths; records without one carry no vortex.")
    texts: tuple[RecordText, ...] = Field(default=(), description="Record words.")
    labelled_ids: tuple[NodeId, ...] = Field(default=(), description="Records that already carry a human label.")
    enrichment: Optional[EnrichmentResult] = Field(default=None, description="Enrichment run over the same ids, for condensed states and shortcut pairs.")
    enrichment_arm: ArmName = Field(default="real-on", description="Arm used from the enrichment run.")

    @model_validator(mode="after")
    def _rules(self):
        if self.positions.spec != POSITIONS_SPEC or self.positions.shape[0] != len(self.ids):
            raise ValueError("positions must be POSITIONS_SPEC with one row per id")
        known = set(self.ids)
        if len(known) != len(self.ids):
            raise ValueError("ids must be unique")
        for name, items in (("strengths", [s.id for s in self.strengths]), ("texts", [t.id for t in self.texts]),
                            ("labelled_ids", list(self.labelled_ids))):
            if len(set(items)) != len(items) or not set(items) <= known:
                raise ValueError(f"{name} must be unique and refer to cloud ids")
        if self.enrichment is not None and tuple(self.enrichment.ids) != self.ids:
            raise ValueError("enrichment must cover exactly the cloud ids in order")
        return self


class PlatePose(_Frozen):
    """The 2D plate inside the fluid: base normal re-aimed by tilt and yaw, offset, phase, spin, slab."""

    origin: Vec3 = Field(description="Frozen origin in the fluid.")
    normal: Vec3 = Field(description="Base plate normal (normalised by the adapter).")
    tilt_deg: Finite = Field(default=0.0, ge=0, le=85, description="Aperture tilt beta away from the base normal.")
    yaw_deg: Finite = Field(default=0.0, ge=-360, le=360, description="Aperture yaw psi: precession about the base normal.")
    offset: Finite = Field(default=0.0, description="Plate offset h* along the effective normal.")
    phase: Finite = Field(default=0.0, description="Plate phase theta (rad): in-plane axes rotate by theta.")
    omega: Finite = Field(default=0.0, description="Global spin rate of the plate, for inertial readings.")
    slab_half_width: Finite = Field(gt=0, description="Slab half-width w along the effective normal.")

    @model_validator(mode="after")
    def _rules(self):
        if _norm(self.normal) < 1e-12:
            raise ValueError("normal must be nonzero")
        return self


class Aperture(_Frozen):
    """Measuring disc on the plate."""

    center: tuple[Finite, Finite] = Field(description="Centre (u, v) in plate coordinates.")
    radius: Finite = Field(gt=0, description="Aperture radius r.")
    ring_samples: int = Field(default=128, ge=8, le=8192, description="Ring samples K.")
    grid: int = Field(default=24, ge=4, le=256, description="Field grid size across the aperture.")


class ProbeRequest(_Frozen):
    """One probe measurement."""

    schema_version: Literal["datamesh-probe/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    cloud: ProbeCloud = Field(description="The fluid.")
    pose: PlatePose = Field(description="Plate pose.")
    aperture: Aperture = Field(description="Aperture.")
    offset_bracket: Bracket = Field(description="Human search window for the plate offset.")
    radius_bracket: Bracket = Field(description="Human search window for the aperture radius.")
    core_radius: Finite = Field(default=0.09, gt=0, le=1, description="Vortex core delta.")
    frame: Literal["plate", "inertial"] = Field(default="plate", description="plate: vortices only; inertial: adds global spin.")
    gradient_floor: Finite = Field(default=1e-8, ge=0, description="Mask eta when mean ring gradient energy is below this.")
    speed_floor: Finite = Field(default=1e-8, ge=0, description="Mask leakage and field points when speed is below this.")

    @model_validator(mode="after")
    def _rules(self):
        if not self.offset_bracket.contains(self.pose.offset):
            raise ValueError("plate offset is outside its bracket")
        if not self.radius_bracket.contains(self.aperture.radius):
            raise ValueError("aperture radius is outside its bracket")
        if self.radius_bracket.lo <= 0:
            raise ValueError("radius bracket must be positive")
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


# ----------------------------------------------------------------------------- readings

class RingReading(_Frozen):
    """Vortex readings on the aperture ring. Each has its own mask."""

    circulation: Finite = Field(description="Signed circulation of the ring.")
    eta_kin: Optional[Finite] = Field(description="Rotation share of squared gradient; None when masked.")
    leakage: Optional[Finite] = Field(description="Radial share of absolute flux; None when masked.")
    winding_status: Literal["invalid", "sampled_only", "certified"] = Field(description="Velocity-index status.")
    sampled_index: Optional[int] = Field(description="Polygon index, when the polygon is safe.")
    certified_index: Optional[int] = Field(description="Continuous-field index under the analytic bound.")
    masks: tuple[str, ...] = Field(description="Which readings were masked and why.")


class FieldReading(_Frozen):
    """Field readings on a grid inside the aperture."""

    mean_vorticity: Optional[Finite] = Field(description="Mean vorticity over unmasked grid points.")
    mean_strain: Optional[Finite] = Field(description="Mean ||S||_F over unmasked grid points.")
    max_speed: Finite = Field(ge=0, description="Max speed over the aperture grid.")
    unmasked_fraction: Finite = Field(ge=0, le=1, description="Grid points above speed_floor.")


class PlaneReading(_Frozen):
    """Local plane of aperture records in the 3D fluid (sign-free)."""

    n_used: NonNegativeInt = Field(description="Aperture records used for the fit.")
    valid: bool = Field(description="At least 3 records and a nondegenerate spread.")
    planarity: Optional[Finite] = Field(description="1 - lambda_min / lambda_mid.")
    tilt_to_plate_deg: Optional[Finite] = Field(description="Unsigned angle between local plane and plate (0 = parallel).")


class StateReading(_Frozen):
    """Counts and density at this pose."""

    total: NonNegativeInt = Field(description="Records in the fluid.")
    in_slab: NonNegativeInt = Field(description="Records taken in by the plate.")
    in_aperture: NonNegativeInt = Field(description="Slab records inside the aperture.")
    with_strength: NonNegativeInt = Field(description="Aperture records with an explicit strength.")
    condensed: Optional[NonNegativeInt] = Field(description="Aperture records with a nonzero sparse code; None without enrichment.")
    labelled: NonNegativeInt = Field(description="Aperture records already labelled.")
    density_ratio: Optional[Finite] = Field(description="Aperture density over slab density (per plate area).")


class SpinGauges(_Frozen):
    """Global and local spin, and the balance of explicit strengths inside the aperture."""

    global_spin: Finite = Field(description="Plate spin rate Omega.")
    local_spin: Optional[Finite] = Field(description="Half the mean vorticity in the aperture.")
    positive_circulation: Finite = Field(ge=0, description="Sum of positive strengths inside the aperture.")
    negative_circulation: Finite = Field(ge=0, description="Sum of |negative strengths| inside the aperture.")
    balance: Optional[Finite] = Field(description="(G+ - G-) / (G+ + G-); None with no vortices inside.")


class ProbeReading(_Frozen):
    """Everything the probe measured at one pose."""

    schema_version: Literal["datamesh-probe/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    request_digest: Digest = Field(description="Digest of the request.")
    result_kind: Literal["embedding_geometry"] = Field(default="embedding_geometry", description="Never an operational forecast.")
    field_model: Literal["regularised point vortices at slab records, explicit strengths"] = Field(
        default="regularised point vortices at slab records, explicit strengths", description="What the vortex and field readings measure.")
    effective_normal: Vec3 = Field(description="Normal after tilt and yaw.")
    axis_u: Vec3 = Field(description="Plate u axis at this phase.")
    axis_v: Vec3 = Field(description="Plate v axis at this phase.")
    offset_state: BracketState = Field(description="Offset in its bracket.")
    radius_state: BracketState = Field(description="Radius in its bracket.")
    ring: RingReading = Field(description="Vortex readings.")
    field: FieldReading = Field(description="Field readings.")
    plane: PlaneReading = Field(description="Plane readings.")
    states: StateReading = Field(description="State readings.")
    spin: SpinGauges = Field(description="Spin gauges.")
    aperture_ids: tuple[NodeId, ...] = Field(description="Aperture records, nearest to the centre first.")
    slab_ids: tuple[NodeId, ...] = Field(description="Slab records, row order of slab_coords.")
    slab_coords: TensorRef = Field(description="Ref to M x 2 plate coordinates of slab records.")


class TermWeight(_Frozen):
    """One word with its weight."""

    term: str = Field(min_length=1, max_length=60, description="Word.")
    weight: Finite = Field(description="Contrast (log-odds) or tf-idf weight.")
    count: NonNegativeInt = Field(description="Occurrences in the lens or record.")


class LensRecord(_Frozen):
    """A record under the lens."""

    id: NodeId = Field(description="Record id.")
    title: Optional[str] = Field(description="Record title, if supplied.")
    distance: Finite = Field(ge=0, description="Plate distance from the pointer.")
    u: Finite = Field(description="Plate u.")
    v: Finite = Field(description="Plate v.")
    labelled: bool = Field(description="Already labelled.")


class LensRequest(_Frozen):
    """Hover and magnify at a pointer on the plate."""

    probe: ProbeRequest = Field(description="Pose and cloud.")
    pointer: tuple[Finite, Finite] = Field(description="Pointer (u, v) in plate coordinates.")
    magnification: Finite = Field(default=1.0, ge=1, le=1000, description="Lens radius = aperture radius / magnification.")
    top_terms: int = Field(default=10, ge=1, le=100, description="Terms returned.")


class LensReading(_Frozen):
    """What the lens shows at the pointer."""

    lens_radius: Finite = Field(gt=0, description="Radius actually used.")
    records: tuple[LensRecord, ...] = Field(description="Records under the lens, nearest first.")
    hovered: Optional[LensRecord] = Field(description="Nearest record, if any.")
    hovered_terms: tuple[TermWeight, ...] = Field(description="Hovered record's tf-idf terms against the slab.")
    contrast_terms: tuple[TermWeight, ...] = Field(description="Lens terms by smoothed log-odds against the slab.")


class CandidateRequest(_Frozen):
    """Cluster the aperture into candidates."""

    probe: ProbeRequest = Field(description="Pose and cloud.")
    k: int = Field(default=5, ge=1, le=50, description="Mutual kNN neighbours.")
    min_size: int = Field(default=3, ge=2, description="Smallest candidate cluster.")
    max_clusters: int = Field(default=24, ge=1, le=500, description="Largest clusters returned.")
    require_condensed: bool = Field(default=False, description="Cluster only records with a nonzero sparse code.")
    top_terms: int = Field(default=5, ge=1, le=50, description="Suggested terms per cluster.")


class CandidateCluster(_Frozen):
    """A cluster of aperture records proposed for labeling."""

    cluster_id: Ident = Field(description="Hash of the sorted member ids.")
    members: tuple[NodeId, ...] = Field(description="Member ids.")
    centroid: tuple[Finite, Finite] = Field(description="Plate centroid.")
    cohesion: Finite = Field(ge=0, le=1, description="1 - mean intra distance / mean aperture distance, clipped.")
    suggested_terms: tuple[str, ...] = Field(description="Contrast terms against the aperture; a naming aid, not a label.")
    status: Literal["candidate"] = Field(default="candidate", description="Never a label until a human records one.")


class PairCandidate(_Frozen):
    """A record pair proposed for labeling."""

    a: NodeId = Field(description="First record.")
    b: NodeId = Field(description="Second record.")
    source: Literal["enrichment_shortcut"] = Field(description="Where the pair came from.")
    score: Finite = Field(ge=0, description="Source score.")
    status: Literal["candidate"] = Field(default="candidate", description="Candidate only.")


class CandidateSet(_Frozen):
    """Candidates at one pose."""

    request_digest: Digest = Field(description="Digest of the probe request.")
    clusters: tuple[CandidateCluster, ...] = Field(description="Clusters, largest first.")
    unclustered: tuple[NodeId, ...] = Field(description="Aperture records in no cluster.")
    pairs: tuple[PairCandidate, ...] = Field(description="Enrichment shortcut pairs with both ends in the aperture.")


class LabelEvent(_Frozen):
    """A human label on a record, cluster or pair. Judgment on a candidate, not validation or authority."""

    target_kind: Literal["record", "cluster", "pair"] = Field(description="What is labelled.")
    target_ids: tuple[NodeId, ...] = Field(min_length=1, max_length=5000, description="Record ids (cluster members or the pair).")
    label: LabelKey = Field(description="Label key.")
    labeler_role: str = Field(min_length=1, max_length=80, description="Role, not a name, in shared artifacts.")
    blind: bool = Field(description="Labelled before unblinding real vs null.")
    occurred_at: datetime = Field(description="Real timestamp of the judgment.")
    reading_digest: Digest = Field(description="Digest of the probe request the label was made on.")
    candidate_ref: Optional[Ident] = Field(default=None, description="Cluster id or pair key the label resolves.")
    note: Optional[str] = Field(default=None, max_length=500, description="Free note.")

    @model_validator(mode="after")
    def _rules(self):
        n = len(self.target_ids)
        if len(set(self.target_ids)) != n:
            raise ValueError("target ids must be unique")
        if (self.target_kind == "record" and n != 1) or (self.target_kind == "pair" and n != 2) or (self.target_kind == "cluster" and n < 2):
            raise ValueError("record needs 1 id, pair 2, cluster at least 2")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return self


CONTRACTS = (Bracket, BracketState, BracketStep, RecordStrength, RecordText, ProbeCloud, PlatePose, Aperture,
             ProbeRequest, RingReading, FieldReading, PlaneReading, StateReading, SpinGauges, ProbeReading,
             TermWeight, LensRecord, LensRequest, LensReading, CandidateRequest, CandidateCluster, PairCandidate,
             CandidateSet, LabelEvent)
INPUT_TENSORS = {"positions": POSITIONS_SPEC}
