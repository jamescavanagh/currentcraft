"""Build an EnrichmentService on the shared tensor store."""

from __future__ import annotations

from app.application.enrichment.services import EnrichmentService
from app.infrastructure.tensors.numpy_store import InMemoryNumpyTensorStore

from .adapters import NumpyEnrichmentAdapter


def build_numpy_enrichment(store: InMemoryNumpyTensorStore | None = None) -> EnrichmentService:
    store = InMemoryNumpyTensorStore() if store is None else store
    return EnrichmentService(store=store, adapter=NumpyEnrichmentAdapter(store))
