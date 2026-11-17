"""Enrichment port. Array-free."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import EnrichmentRequest, EnrichmentResult


@runtime_checkable
class EmbeddingEnrichmentPort(Protocol):
    def enrich(self, request: EnrichmentRequest) -> EnrichmentResult: ...
