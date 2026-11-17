"""Build a SimulationService wired to numpy adapters. Kept out of container.py until wiring decisions land."""

from __future__ import annotations

from app.application.simulation.services import SimulationService

from .numpy_adapters import (NumpyBufferRingAdapter, NumpyCnnSampleAdapter, NumpyGraphTensorAdapter,
                             NumpyNodeInteractionAdapter, NumpyTensorTransformAdapter)
from .numpy_store import InMemoryNumpyTensorStore


def build_numpy_simulation(store: InMemoryNumpyTensorStore | None = None):
    """Return (service, store, transforms)."""
    store = InMemoryNumpyTensorStore() if store is None else store
    service = SimulationService(store=store, interactions=NumpyNodeInteractionAdapter(store),
                                rings=NumpyBufferRingAdapter(store), cnn=NumpyCnnSampleAdapter(store),
                                graphs=NumpyGraphTensorAdapter(store))
    return service, store, NumpyTensorTransformAdapter(store)
