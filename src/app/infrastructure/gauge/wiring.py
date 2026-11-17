"""Build a GaugeService wired to numpy adapters. Pass the store from build_numpy_simulation to share refs across slices."""

from __future__ import annotations

from app.application.gauge.services import GaugeService
from app.infrastructure.tensors.numpy_store import InMemoryNumpyTensorStore

from .numpy_adapters import NumpyGaugeInvarianceAdapter, NumpyGaugeReductionAdapter, NumpyParticipationNullAdapter


def build_numpy_gauge(store: InMemoryNumpyTensorStore | None = None):
    """Return (service, store)."""
    store = InMemoryNumpyTensorStore() if store is None else store  # an empty store is falsy (__len__)
    service = GaugeService(store=store, reduction=NumpyGaugeReductionAdapter(store),
                           invariance=NumpyGaugeInvarianceAdapter(store), nulls=NumpyParticipationNullAdapter(store))
    return service, store
