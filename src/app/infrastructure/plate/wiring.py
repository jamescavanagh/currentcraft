"""Build a PlateService on numpy adapters, the shared tensor store and a broker."""

from __future__ import annotations

from app.application.plate.services import PlateService
from app.infrastructure.gauge.winding import NumpyVelocityWindingAdapter
from app.infrastructure.messaging.memory import InMemoryBroker
from app.infrastructure.tensors.numpy_store import InMemoryNumpyTensorStore

from .adapters import NumpyArcBoundAdapter, NumpyPlateDynamicsAdapter, NumpyPlateFieldAdapter


def build_numpy_plate(store: InMemoryNumpyTensorStore | None = None, broker=None):
    """Return (service, store, broker). Pass existing ones to share refs and events across slices."""
    store = InMemoryNumpyTensorStore() if store is None else store  # an empty store is falsy
    broker = InMemoryBroker() if broker is None else broker
    service = PlateService(store=store, dynamics=NumpyPlateDynamicsAdapter(store), field=NumpyPlateFieldAdapter(store),
                           bounds=NumpyArcBoundAdapter(store), winding=NumpyVelocityWindingAdapter(store), broker=broker)
    return service, store, broker
