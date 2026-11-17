"""Build the HFGT capability-graph adapter on a numpy tensor store."""
from __future__ import annotations

from app.infrastructure.tensors.numpy_store import InMemoryNumpyTensorStore

from .adapters import NumpyHfgtGraphAdapter


def build_hfgt(store: InMemoryNumpyTensorStore | None = None):
    """Return (adapter, store)."""
    store = InMemoryNumpyTensorStore() if store is None else store
    return NumpyHfgtGraphAdapter(store), store
