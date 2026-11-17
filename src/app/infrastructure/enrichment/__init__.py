"""Numpy-backed enrichment adapter and chamber kernels. The only place enrichment arrays exist."""

from .adapters import NumpyEnrichmentAdapter, put_embedding_matrix, put_labels  # noqa: F401
from .wiring import build_numpy_enrichment  # noqa: F401
