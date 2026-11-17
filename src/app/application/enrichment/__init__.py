"""Embedding enrichment application layer. Pydantic only; arrays live in app.infrastructure.enrichment."""

from .contracts import (ANOMALOUS, ARMS, CONTRACTS, INPUT_TENSORS, ORDERS, PHASE_BINS, SCHEMA_VERSION,  # noqa: F401
                        TENSOR_CONTRACTS, ArmStats, ChamberParams, EnrichmentRequest, EnrichmentResult, PassRecord,
                        ShortcutCandidate, ShortcutCriteria, SlabFrame, SmallWorldStats)
from .ports import EmbeddingEnrichmentPort  # noqa: F401
from .services import EnrichmentService  # noqa: F401
