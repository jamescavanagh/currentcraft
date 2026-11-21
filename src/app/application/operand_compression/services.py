"""Optional geometry orchestration; never used by feature-graph validation."""
from app.application.gauge.services import GaugeService
from .contracts import OperandCompressionRequest, OperandCompressionResult


class OperandCompressionService:
    def __init__(self, gauge: GaugeService):
        self.gauge = gauge

    def compress(self, request: OperandCompressionRequest) -> OperandCompressionResult:
        gauge_result, invariance = self.gauge.reduce_checked(request.as_gauge_request())
        return OperandCompressionResult(request_digest=request.digest(),
            domain_contexts=tuple(dict.fromkeys(p.operand.domain_context for p in request.profiles)),
            profile_ids=tuple(str(p.profile_id) for p in request.profiles),
            operand_ids=tuple(str(p.operand.object_id) for p in request.profiles),
            gauge_result=gauge_result, invariance=invariance)
