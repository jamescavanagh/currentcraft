"""Plate + spatial isosceles three-body contracts. Pydantic only; design source docs/pipelines/PLATE_ISOSCELES.md.

Results are simulated model state, never business locations. Snapshots are inertial.
"""

from __future__ import annotations

import hashlib
import math
from typing import Annotated, ClassVar, Literal, Optional

from pydantic import Field, NonNegativeInt, StringConstraints, model_validator

from app.application.gauge.winding import ANGLES_SPEC, BOUND_SPEC, VELOCITY_SPEC  # noqa: F401 (shared winding specs)
from app.application.simulation.contracts import NodeId, TensorContract
from app.application.common.contracts import _Frozen
from app.application.simulation.tensors import TensorRef, TensorSpec

SCHEMA_VERSION = "datamesh-plate/v1"
Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Finite = Annotated[float, Field(allow_inf_nan=False)]

BODY_NAMES = ("side_a", "side_b", "object")
PLATE_FEATURES = ("height", "phase", "omega", "side_radius", "angular_momentum_z", "zeta", "zeta_dot", "energy",
                  "mirror_error")
PLATE_FEATURE_MEANINGS = {
    "height": "Plate height: mean z of the side bodies (inertial, COM frame).",
    "phase": "Plate phase theta of side body A, unwrapped (rad, inertial).",
    "omega": "Plate spin rate d theta / dt (rad per model time).",
    "side_radius": "Distance r of each side body from the axis.",
    "angular_momentum_z": "Global spin L_z of all three bodies about the axis.",
    "zeta": "Object height above the plate, w - z; positive is the + side.",
    "zeta_dot": "Rate of zeta.",
    "energy": "Total energy (Plummer-softened); baseline resets at mass events.",
    "mirror_error": "Symmetry diagnostic: max of |A_xy + B_xy|, |z_A - z_B|, |O_xy|.",
}


def _spec(name, dims, shape, description, unit=None, min_value=None):
    return TensorSpec(name="plate." + name, dims=dims, shape=shape, dtype="float64", unit=unit,
                      description=description, min_value=min_value)


TIMES_SPEC = _spec("times", ("snapshot",), ("T",), "Model time of each snapshot, strictly increasing.", unit="model time")
POSITIONS_SPEC = _spec("positions", ("snapshot", "body", "axis"), ("T", 3, 3), "Inertial COM-frame positions of side_a, side_b, object.")
VELOCITIES_SPEC = _spec("velocities", ("snapshot", "body", "axis"), ("T", 3, 3), "Inertial velocities of side_a, side_b, object.")
MASSES_SPEC = _spec("masses", ("snapshot", "body"), ("T", 3), "Body masses at each snapshot; the object mass changes only at mass events.", min_value=0)
READOUT_SPEC = _spec("readout", ("snapshot", "feature"), ("T", len(PLATE_FEATURES)), "Plate readouts, columns PLATE_FEATURES.")
POINTS_SPEC = _spec("points", ("point", "component"), ("K", 2), "Sample points in the requested frame.")
FIELD_VELOCITY_SPEC = _spec("field_velocity", ("point", "component"), ("K", 2), "Plate field velocity at the sample points.")
FIELD_JACOBIAN_SPEC = _spec("field_jacobian", ("point", "row", "column"), ("K", 2, 2), "Analytic velocity Jacobian du_i / dx_j at the sample points.")


class IsoscelesParams(_Frozen):
    """Spatial isosceles initial condition: two mirrored side bodies on the plate, the object body on the axis."""

    side_mass: Finite = Field(default=1.0, gt=0, le=100, description="Mass m of each side body.")
    object_mass: Finite = Field(default=0.3, gt=0, le=100, description="Initial object mass m3.")
    side_radius: Finite = Field(default=1.0, gt=0, le=10, description="Initial distance r of each side body from the axis.")
    spin_factor: Finite = Field(default=1.0, gt=0, le=3, description="Side speed as a multiple of the instantaneous circular speed.")
    zeta0: Finite = Field(default=0.7, ge=-10, le=10, description="Initial object height above the plate; nonzero.")
    zeta_dot0: Finite = Field(default=0.0, ge=-10, le=10, description="Initial rate of zeta.")
    softening: Finite = Field(default=0.03, ge=0, le=1, description="Plummer softening epsilon.")

    @model_validator(mode="after")
    def _nonzero(self):
        if self.zeta0 == 0:
            raise ValueError("zeta0 must be nonzero so the starting side is defined")
        return self


class PlateVortex(_Frozen):
    """A local vortex pinned in the plate frame. Strength is given explicitly, never inferred from projection handedness."""

    id: NodeId = Field(description="Stable vortex id.")
    u: Finite = Field(ge=-10, le=10, description="Plate-frame x.")
    v: Finite = Field(ge=-10, le=10, description="Plate-frame y.")
    strength: Finite = Field(ge=-10, le=10, description="Circulation Gamma; sign is spin direction, not good or bad.")
    source_ref: Optional[str] = Field(default=None, max_length=200, description="Evidence for position and strength.")


class ObjectMassEvent(_Frozen):
    """Live change of the object mass, e.g. a gate's held load. The run continues; nothing resets."""

    t: Finite = Field(gt=0, description="Model time at which the new mass applies (first step boundary at or after t).")
    object_mass: Finite = Field(gt=0, le=100, description="New object mass.")
    cause: str = Field(min_length=1, max_length=200, description="Why the mass changed.")
    source_ref: Optional[str] = Field(default=None, max_length=200, description="Event provenance.")


def _unique_vortices(vs) -> None:
    ids = [v.id for v in vs]
    if len(set(ids)) != len(ids):
        raise ValueError("vortex ids must be unique")


class PlateRunRequest(_Frozen):
    """One simulated plate run."""

    schema_version: Literal["datamesh-plate/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    plate_id: Ident = Field(description="Plate id; used in broker topics.")
    object_id: Optional[Ident] = Field(default=None, description="Object riding the axis; crossings carry it.")
    params: IsoscelesParams = Field(default_factory=IsoscelesParams, description="Initial condition.")
    vortices: tuple[PlateVortex, ...] = Field(default=(), max_length=64, description="Local vortices in the plate frame.")
    plate_radius: Finite = Field(default=1.8, gt=0, le=20, description="Plate radius (field domain).")
    core_radius: Finite = Field(default=0.09, gt=0, le=1, description="Vortex core delta.")
    dt: Finite = Field(default=0.002, gt=0, le=0.05, description="Integrator step.")
    steps: int = Field(default=20000, ge=1, le=2_000_000, description="Number of steps.")
    record_every: int = Field(default=20, ge=1, description="Snapshot stride in steps.")
    mass_events: tuple[ObjectMassEvent, ...] = Field(default=(), max_length=1000, description="Live mass changes, strictly increasing t.")
    escape_zeta: Finite = Field(default=9.0, gt=0, description="Stop as escaped when |zeta| exceeds this.")
    escape_radius: Finite = Field(default=6.0, gt=0, description="Stop as escaped when r exceeds this.")
    publish: bool = Field(default=True, description="Publish crossing and run events when a broker is wired.")

    @model_validator(mode="after")
    def _rules(self):
        _unique_vortices(self.vortices)
        ts = [e.t for e in self.mass_events]
        if any(b <= a for a, b in zip(ts, ts[1:])):
            raise ValueError("mass events must be strictly increasing in t")
        if ts and ts[-1] >= self.dt * self.steps:
            raise ValueError("mass events must fall inside the run")
        if self.params.side_radius >= self.plate_radius:
            raise ValueError("side bodies must start inside the plate")
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class PlateCrossing(_Frozen):
    """The object body passing through the plate plane: a simulated, candidate-only event."""

    index: NonNegativeInt = Field(description="Crossing number within the run.")
    t: Finite = Field(description="Crossing time, linearly interpolated within the step.")
    direction: Literal[-1, 1] = Field(description="+1 moving to the + side, -1 moving to the - side.")
    side_after: Literal["+", "-"] = Field(description="Slice side after the crossing; not good or bad.")
    plate_height: Finite = Field(description="Plate height at the crossing step.")
    plate_phase: Finite = Field(description="Unwrapped inertial plate phase at the crossing step.")
    radial_offset: Finite = Field(ge=0, description="Object distance from the axis; 0 under exact symmetry.")


class PlateRunResult(TensorContract):
    """Inertial trajectories, plate readouts, crossings and integrity diagnostics."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {"times": TIMES_SPEC, "positions": POSITIONS_SPEC,
                                                "velocities": VELOCITIES_SPEC, "masses": MASSES_SPEC,
                                                "plate": READOUT_SPEC}
    PRODUCED_BY: ClassVar[str] = "PlateDynamicsPort"

    schema_version: Literal["datamesh-plate/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    plate_id: Ident = Field(description="Plate id from the request.")
    object_id: Optional[Ident] = Field(description="Object id from the request.")
    request_digest: Digest = Field(description="Digest of the complete request.")
    frame: Literal["inertial"] = Field(default="inertial", description="Snapshots are always inertial; the co-rotating frame discards phase.")
    epistemic_status: Literal["simulated"] = Field(default="simulated", description="Model state, never computed evidence.")
    status: Literal["ok", "escaped"] = Field(description="escaped when |zeta| or r exceeded the request limits.")
    steps_run: NonNegativeInt = Field(description="Steps actually integrated.")
    t_end: Finite = Field(description="Model time at the end of the run.")
    body_names: tuple[str, ...] = Field(default=BODY_NAMES, description="Axis 'body' order.")
    feature_names: tuple[str, ...] = Field(default=PLATE_FEATURES, description="Axis 'feature' order of plate.")
    crossings: tuple[PlateCrossing, ...] = Field(description="Every crossing of the plate plane.")
    mass_events_applied: tuple[Finite, ...] = Field(description="Requested times of mass events that were applied.")
    max_relative_energy_drift: Finite = Field(ge=0, description="Max |E - E_seg| / |E_seg| over snapshots, per mass-event segment.")
    max_angular_momentum_drift: Finite = Field(ge=0, description="Max |L_z - L_z,seg| over snapshots, per segment.")
    max_mirror_error: Finite = Field(ge=0, description="Max mirror_error over snapshots.")
    times: TensorRef = Field(description="Ref to T snapshot times.")
    positions: TensorRef = Field(description="Ref to T x 3 x 3 positions.")
    velocities: TensorRef = Field(description="Ref to T x 3 x 3 velocities.")
    masses: TensorRef = Field(description="Ref to T x 3 masses.")
    plate: TensorRef = Field(description="Ref to T x F plate readouts.")


class PlateFieldRequest(_Frozen):
    """Sample the plate field (global spin + local vortices) and its analytic Jacobian at points."""

    vortices: tuple[PlateVortex, ...] = Field(description="Local vortices in the plate frame.")
    core_radius: Finite = Field(default=0.09, gt=0, le=1, description="Vortex core delta.")
    frame: Literal["plate", "inertial"] = Field(default="plate", description="plate: vortices only; inertial: adds Omega J x and rotates by phase.")
    omega: Finite = Field(default=0.0, description="Global spin rate; must be 0 in the plate frame.")
    phase: Finite = Field(default=0.0, description="Plate phase; must be 0 in the plate frame.")
    points: TensorRef = Field(description="K x 2 POINTS_SPEC sample points in the requested frame.")

    @model_validator(mode="after")
    def _rules(self):
        _unique_vortices(self.vortices)
        if self.points.spec != POINTS_SPEC:
            raise ValueError("points must use POINTS_SPEC")
        if self.frame == "plate" and (self.omega != 0 or self.phase != 0):
            raise ValueError("plate frame has no global spin or phase")
        return self


class PlateFieldResult(TensorContract):
    """Velocity and analytic Jacobian of the plate field."""

    TENSORS: ClassVar[dict[str, TensorSpec]] = {"velocity": FIELD_VELOCITY_SPEC, "jacobian": FIELD_JACOBIAN_SPEC}
    PRODUCED_BY: ClassVar[str] = "PlateFieldPort"
    frame: Literal["plate", "inertial"] = Field(description="Frame of the values.")
    epistemic_status: Literal["simulated"] = Field(default="simulated", description="Model field, not measured flow.")
    velocity: TensorRef = Field(description="Ref to K x 2 velocities.")
    jacobian: TensorRef = Field(description="Ref to K x 2 x 2 Jacobians.")


class RingWindingRequest(_Frozen):
    """A ring on the plate for a velocity-index reading with an analytic whole-arc derivative bound."""

    vortices: tuple[PlateVortex, ...] = Field(description="Local vortices in the plate frame.")
    core_radius: Finite = Field(default=0.09, gt=0, le=1, description="Vortex core delta.")
    center: tuple[Finite, Finite] = Field(description="Ring centre in the requested frame.")
    radius: Finite = Field(gt=0, description="Ring radius.")
    samples: int = Field(default=128, ge=3, le=65536, description="Evenly spaced samples K.")
    frame: Literal["plate", "inertial"] = Field(default="plate", description="Frame of the ring and velocities.")
    omega: Finite = Field(default=0.0, description="Global spin rate; must be 0 in the plate frame.")
    phase: Finite = Field(default=0.0, description="Plate phase; must be 0 in the plate frame.")
    plate_radius: Finite = Field(default=1.8, gt=0, description="The ring must lie on the plate.")
    point_floor: Finite = Field(default=1e-10, ge=0, description="Velocity-space zero exclusion threshold.")
    phase_margin: Finite = Field(default=0.05, gt=0, lt=math.pi, description="Max wrapped phase step margin.")

    @model_validator(mode="after")
    def _rules(self):
        _unique_vortices(self.vortices)
        if self.frame == "plate" and (self.omega != 0 or self.phase != 0):
            raise ValueError("plate frame has no global spin or phase")
        if math.hypot(*self.center) + self.radius > self.plate_radius:
            raise ValueError("ring must lie on the plate")
        return self


class ArcBoundResult(_Frozen):
    """Ring samples plus whole-segment derivative bounds, as shared winding TensorRefs."""

    velocity: TensorRef = Field(description="K x 2 ring velocities (winding VELOCITY_SPEC).")
    angles: TensorRef = Field(description="K ring angles (winding ANGLES_SPEC).")
    derivative_bound: TensorRef = Field(description="K whole-segment bounds on ||du/ds|| (winding BOUND_SPEC).")
    provenance: str = Field(min_length=1, max_length=500, description="How the bound was derived.")


CONTRACTS = (IsoscelesParams, PlateVortex, ObjectMassEvent, PlateRunRequest, PlateCrossing, PlateRunResult,
             PlateFieldRequest, PlateFieldResult, RingWindingRequest, ArcBoundResult)
TENSOR_CONTRACTS = (PlateRunResult, PlateFieldResult)
INPUT_TENSORS = {"points": POINTS_SPEC}
