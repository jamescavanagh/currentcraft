"""Pure evidence chunk contracts; no extraction, storage or source access."""
from .contracts import (
    CONTRACTS, SCHEMA_VERSION, EvidenceCellRange, EvidenceChunk,
    EvidenceChunkSet, EvidenceProvenance, EvidenceTextOffsets,
)

__all__ = ["CONTRACTS", "SCHEMA_VERSION", *[c.__name__ for c in CONTRACTS]]
