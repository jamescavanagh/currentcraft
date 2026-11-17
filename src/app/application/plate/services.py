"""Plate use cases: run and publish, sample the field, certify ring winding through the shared winding port."""

from __future__ import annotations

from typing import Optional

from app.application.gauge.winding import VelocityWindingPort, VelocityWindingRequest, VelocityWindingResult
from app.application.messaging.contracts import make_event
from app.application.messaging.ports import MessageBrokerPort
from app.application.simulation.ports import TensorStorePort
from app.application.simulation.tensors import TensorContractError

from .contracts import PlateFieldRequest, PlateFieldResult, PlateRunRequest, PlateRunResult, RingWindingRequest
from .ports import ArcBoundPort, PlateDynamicsPort, PlateFieldPort


class PlateService:
    def __init__(self, store: TensorStorePort, dynamics: PlateDynamicsPort, field: PlateFieldPort, bounds: ArcBoundPort,
                 winding: VelocityWindingPort, broker: Optional[MessageBrokerPort] = None):
        self.store, self.dynamics, self.field, self.bounds, self.winding, self.broker = store, dynamics, field, bounds, winding, broker

    def run(self, request: PlateRunRequest) -> PlateRunResult:
        result = self.dynamics.run(request)
        if result.request_digest != request.digest():
            raise TensorContractError("plate run provenance mismatch")
        if any(not self.store.contains(r) for r in result.tensor_refs().values()):
            raise TensorContractError("plate run refs not in shared store")
        if self.broker is not None and request.publish:
            self._publish(request, result)
        return result

    def _publish(self, request: PlateRunRequest, result: PlateRunResult) -> None:
        chain = "run-" + result.request_digest[:24]
        base = {"plate_id": result.plate_id, "object_id": result.object_id, "request_digest": result.request_digest}
        for c in result.crossings:
            self.broker.publish(make_event(
                topic=f"plate/{result.plate_id}/crossing", kind="plate.crossing", source=result.plate_id,
                epistemic_status="simulated", sim_time=c.t, correlation_id=chain,
                payload={**base, "index": c.index, "direction": c.direction, "side_after": c.side_after,
                         "plate_height": c.plate_height, "plate_phase": c.plate_phase, "radial_offset": c.radial_offset}))
        self.broker.publish(make_event(
            topic=f"plate/{result.plate_id}/run", kind="plate.run", source=result.plate_id, epistemic_status="simulated",
            sim_time=result.t_end, correlation_id=chain,
            payload={**base, "status": result.status, "steps_run": result.steps_run, "crossings": len(result.crossings),
                     "max_relative_energy_drift": result.max_relative_energy_drift,
                     "max_mirror_error": result.max_mirror_error,
                     "plate_key": result.plate.key, "plate_sha256": result.plate.sha256}))

    def sample_field(self, request: PlateFieldRequest) -> PlateFieldResult:
        if not self.store.contains(request.points):
            raise TensorContractError("points not in shared store")
        return self.field.sample(request)

    def ring_winding(self, request: RingWindingRequest) -> VelocityWindingResult:
        """Velocity index on a plate ring; certified only under the analytic whole-arc bound."""
        b = self.bounds.bound(request)
        return self.winding.measure(VelocityWindingRequest(
            velocity=b.velocity, angles=b.angles, radius=request.radius, point_floor=request.point_floor,
            phase_margin=request.phase_margin, derivative_bound=b.derivative_bound, bound_provenance=b.provenance))
