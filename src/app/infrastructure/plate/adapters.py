"""Numpy adapters implementing the plate ports against the shared tensor store."""

from __future__ import annotations

import numpy as np

from app.application.gauge.winding import ANGLES_SPEC, BOUND_SPEC, VELOCITY_SPEC
from app.application.plate.contracts import (FIELD_JACOBIAN_SPEC, FIELD_VELOCITY_SPEC, MASSES_SPEC, POINTS_SPEC,
                                             POSITIONS_SPEC, READOUT_SPEC, TIMES_SPEC, VELOCITIES_SPEC, ArcBoundResult,
                                             PlateCrossing, PlateFieldRequest, PlateFieldResult, PlateRunRequest,
                                             PlateRunResult, RingWindingRequest)
from app.application.simulation.tensors import TensorContractError

from . import kernels as K

BOUND_PROVENANCE = ("analytic whole-arc bound: |Omega| (inertial) + sum_k |Gamma_k| / (2 pi (d_ke^2 + delta^2)), "
                    "d_ke exact vortex-to-arc distance; Rosenhead-Moore regularised vortices (datamesh-plate/v1)")


def _vortex_array(vortices):
    return np.array([[v.u, v.v, v.strength] for v in vortices], dtype=np.float64).reshape(-1, 3)


class NumpyPlateDynamicsAdapter:
    def __init__(self, store):
        self.store = store

    def run(self, request: PlateRunRequest) -> PlateRunResult:
        p = request.params
        out = K.run_isosceles(side_mass=p.side_mass, object_mass=p.object_mass, side_radius=p.side_radius,
                              spin_factor=p.spin_factor, zeta0=p.zeta0, zeta_dot0=p.zeta_dot0, softening=p.softening,
                              dt=request.dt, steps=request.steps, record_every=request.record_every,
                              mass_events=[(e.t, e.object_mass) for e in request.mass_events],
                              escape_zeta=request.escape_zeta, escape_radius=request.escape_radius)
        put = lambda spec, a: self.store.put(spec, np.ascontiguousarray(a, dtype=np.float64), producer="NumpyPlateDynamicsAdapter")
        return PlateRunResult(plate_id=request.plate_id, object_id=request.object_id, request_digest=request.digest(),
                              status=out["status"], steps_run=out["steps_run"], t_end=out["t_end"],
                              crossings=tuple(PlateCrossing(**c) for c in out["crossings"]),
                              mass_events_applied=tuple(out["applied"]),
                              max_relative_energy_drift=out["max_e"], max_angular_momentum_drift=out["max_l"],
                              max_mirror_error=out["max_mirror"],
                              times=put(TIMES_SPEC, out["times"]), positions=put(POSITIONS_SPEC, out["positions"]),
                              velocities=put(VELOCITIES_SPEC, out["velocities"]), masses=put(MASSES_SPEC, out["masses"]),
                              plate=put(READOUT_SPEC, out["plate"]))


class NumpyPlateFieldAdapter:
    def __init__(self, store):
        self.store = store

    def sample(self, request: PlateFieldRequest) -> PlateFieldResult:
        if not self.store.contains(request.points):
            raise TensorContractError("points not in shared store")
        vel, jac = K.field_in_frame(self.store.get(request.points), _vortex_array(request.vortices), request.core_radius,
                                    request.frame, request.omega, request.phase)
        prod = "NumpyPlateFieldAdapter"
        return PlateFieldResult(frame=request.frame, velocity=self.store.put(FIELD_VELOCITY_SPEC, vel, producer=prod),
                                jacobian=self.store.put(FIELD_JACOBIAN_SPEC, jac, producer=prod))


class NumpyArcBoundAdapter:
    def __init__(self, store):
        self.store = store

    def bound(self, request: RingWindingRequest) -> ArcBoundResult:
        vel, phi, b = K.ring_samples_and_bounds(_vortex_array(request.vortices), request.core_radius, request.center,
                                                request.radius, request.samples, request.frame, request.omega,
                                                request.phase)
        prod = "NumpyArcBoundAdapter"
        return ArcBoundResult(velocity=self.store.put(VELOCITY_SPEC, vel, producer=prod),
                              angles=self.store.put(ANGLES_SPEC, phi, producer=prod),
                              derivative_bound=self.store.put(BOUND_SPEC, b, producer=prod),
                              provenance=BOUND_PROVENANCE)


def put_points(store, points):
    """Explicit infrastructure conversion of sample points into the shared store."""
    return store.put(POINTS_SPEC, np.array(points, dtype=np.float64, copy=True), producer="plate-input")
