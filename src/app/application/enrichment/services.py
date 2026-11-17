"""Enrichment use case with provenance checks."""

from __future__ import annotations

from app.application.simulation.ports import TensorStorePort
from app.application.simulation.tensors import TensorContractError

from .contracts import EnrichmentRequest, EnrichmentResult
from .ports import EmbeddingEnrichmentPort


class EnrichmentService:
    def __init__(self, store: TensorStorePort, adapter: EmbeddingEnrichmentPort):
        self.store, self.adapter = store, adapter

    def enrich(self, request: EnrichmentRequest) -> EnrichmentResult:
        refs = [request.embeddings, request.labels_real, request.labels_null, request.plate_run.plate, request.plate_run.times]
        if any(r is not None and not self.store.contains(r) for r in refs):
            raise TensorContractError("enrichment inputs not in shared store")
        r = self.adapter.enrich(request)
        if r.request_digest != request.digest() or r.embeddings_sha256 != request.embeddings.sha256:
            raise TensorContractError("enrichment provenance mismatch")
        if any(not self.store.contains(ref) for ref in r.tensor_refs().values()):
            raise TensorContractError("enrichment output refs not in shared store")
        return r
