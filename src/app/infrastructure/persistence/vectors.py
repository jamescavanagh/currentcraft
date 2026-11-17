"""pgvector text literals. The domain is zero-based; pgvector sparsevec is one-based. Conversion happens only here."""

from __future__ import annotations

import math
import re


def _num(v: float) -> str:
    if not math.isfinite(v):
        raise ValueError("vectors must be finite")
    return repr(float(v))


def dense_literal(values) -> str:
    return "[" + ",".join(_num(v) for v in values) + "]"


def sparse_literal(indices, values, dim: int) -> str:
    """Zero-based indices -> '{i+1:v,...}/dim'."""
    if any(i < 0 or i >= dim for i in indices):
        raise ValueError("index out of range")
    return "{" + ",".join(f"{i + 1}:{_num(v)}" for i, v in zip(indices, values)) + f"}}/{dim}"


_SPARSE = re.compile(r"^\{(.*)\}/(\d+)$")


def parse_sparse(text: str) -> tuple[tuple[int, ...], tuple[float, ...], int]:
    """'{i:v,...}/dim' (one-based) -> zero-based indices, values, dim."""
    m = _SPARSE.match(text.strip())
    if not m:
        raise ValueError("not a sparsevec literal")
    body, dim = m.group(1), int(m.group(2))
    pairs = [p.split(":") for p in body.split(",") if p]
    idx = tuple(int(i) - 1 for i, _ in pairs)
    if any(i < 0 or i >= dim for i in idx):
        raise ValueError("index out of range")
    return idx, tuple(float(v) for _, v in pairs), dim
