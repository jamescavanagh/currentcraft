"""Optional NumPy composition reusing the checked gauge and shared tensor store."""
from app.application.operand_compression import OperandCompressionService
from app.infrastructure.gauge import build_numpy_gauge


def build_numpy_operand_compression(store=None):
    gauge, store = build_numpy_gauge(store)
    return OperandCompressionService(gauge), store
