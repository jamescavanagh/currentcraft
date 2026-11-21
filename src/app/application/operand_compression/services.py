"""Application orchestration over the existing checked GaugeService."""
from __future__ import annotations

from app.application.gauge.services import GaugeService

from .contracts import OperandCompressionRequest, OperandCompressionResult


class OperandCompressionService:
    """Convert explicit operand references to existing GaugeNode contracts, then require checked invariance."""

    def __init__(self, gauge: GaugeService):
        self.gauge = gauge

    def compress(self, request: OperandCompressionRequest) -> OperandCompressionResult:
        gauge_request = request.as_gauge_request()
        gauge_result, invariance = self.gauge.reduce_checked(gauge_request)
        return OperandCompressionResult(
            request_digest=request.digest(),
            domain_contexts=tuple(dict.fromkeys(profile.operand.domain_context for profile in request.profiles)),
            profile_ids=tuple(profile.profile_id for profile in request.profiles),
            operand_ids=tuple(str(profile.operand.object_id) for profile in request.profiles),
            gauge_result=gauge_result,
            invariance=invariance,
        )
