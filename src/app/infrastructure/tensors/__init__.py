"""Numpy-backed tensor store and simulation adapters."""

from .numpy_store import InMemoryNumpyTensorStore, ValidatedArray, tensor_sha256  # noqa: F401
from .wiring import build_numpy_simulation  # noqa: F401
