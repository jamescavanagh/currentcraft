"""NumPy-backed composition reusing the existing tensor store and gauge adapters."""
from __future__ import annotations

from app.application.operand_compression import OperandCompressionService
from app.infrastructure.gauge import build_numpy_gauge


def build_numpy_operand_compression(store=None):
    """Return (service, store); embeddings and all result arrays use the shared tensor store."""
    gauge, store = build_numpy_gauge(store)
    return OperandCompressionService(gauge), store
