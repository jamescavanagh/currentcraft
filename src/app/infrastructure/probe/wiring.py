"""Build a ProbeService (and broker) on the shared tensor store."""

from __future__ import annotations

from app.application.probe.services import ProbeService
from app.infrastructure.messaging.memory import InMemoryBroker
from app.infrastructure.tensors.numpy_store import InMemoryNumpyTensorStore

from .adapters import NumpyCandidateAdapter, NumpyLensAdapter, NumpyProbeAdapter


def build_numpy_probe(store: InMemoryNumpyTensorStore | None = None, broker=None):
    """Return (service, store, broker)."""
    store = InMemoryNumpyTensorStore() if store is None else store
    broker = InMemoryBroker() if broker is None else broker
    return ProbeService(store=store, probe=NumpyProbeAdapter(store), lens=NumpyLensAdapter(store),
                        candidates=NumpyCandidateAdapter(store)), store, broker
