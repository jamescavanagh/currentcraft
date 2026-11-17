"""Numpy tensor store and array validation. The only place arrays and TensorRefs meet.

``ValidatedArray`` is a Pydantic model that holds a real ``np.ndarray`` and checks it against a
``TensorSpec`` (shape with symbol bindings, dtype, finiteness, bounds). It lives here because it
imports numpy; application contracts only ever see the resulting ``TensorRef``.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Mapping, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, PlainValidator, ValidationError, model_validator

from app.application.simulation.tensors import TensorContractError, TensorRef, TensorSpec, TensorStats


def _ensure_ndarray(v: Any) -> np.ndarray:
    if not isinstance(v, np.ndarray):
        raise TypeError(f"expected numpy.ndarray, got {type(v).__name__}")
    return v


NDArray = Annotated[np.ndarray, PlainValidator(_ensure_ndarray)]


class ValidatedArray(BaseModel):
    """An array proven to satisfy a TensorSpec. Never casts: a dtype mismatch is an error."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    spec: TensorSpec
    array: NDArray
    bindings: dict[str, int] = {}

    @model_validator(mode="after")
    def _check(self):
        a, s = self.array, self.spec
        if str(a.dtype) != s.dtype:
            raise TensorContractError(f"{s.name}: dtype {a.dtype} != {s.dtype}")
        object.__setattr__(self, "bindings", s.bind(a.shape, self.bindings))
        if a.size and a.dtype.kind == "f":
            if s.finite and not np.isfinite(a).all():
                raise TensorContractError(f"{s.name}: non-finite values")
        if a.size and a.dtype.kind in "fiu":
            finite = a[np.isfinite(a)] if a.dtype.kind == "f" else a
            if finite.size and s.min_value is not None and float(finite.min()) < s.min_value:
                raise TensorContractError(f"{s.name}: value {float(finite.min())} < min {s.min_value}")
            if finite.size and s.max_value is not None and float(finite.max()) > s.max_value:
                raise TensorContractError(f"{s.name}: value {float(finite.max())} > max {s.max_value}")
        return self


def tensor_sha256(a: np.ndarray) -> str:
    """Canonical digest: dtype + shape header, then C-order bytes."""
    h = hashlib.sha256(f"{a.dtype.str}|{a.shape}|".encode())
    h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def _stats(a: np.ndarray) -> TensorStats:
    if not a.size or a.dtype.kind not in "fiub":
        return TensorStats()
    x = a.astype(np.float64)
    fin = np.isfinite(x)
    if not fin.any():
        return TensorStats(nonfinite=int(x.size))
    v = x[fin]
    return TensorStats(min=float(v.min()), max=float(v.max()), mean=float(v.mean()), nonfinite=int((~fin).sum()))


class InMemoryNumpyTensorStore:
    """Implements TensorStorePort. Content-addressed: equal arrays under one spec share a key."""

    def __init__(self) -> None:
        self._arrays: dict[str, np.ndarray] = {}
        self._refs: dict[str, TensorRef] = {}

    # infra-only API -------------------------------------------------------
    def put(self, spec: TensorSpec, array: np.ndarray, producer: str, bindings: Optional[Mapping[str, int]] = None) -> TensorRef:
        try:
            va = ValidatedArray(spec=spec, array=array, bindings=dict(bindings or {}))
        except ValidationError as e:  # surface one domain error type to callers
            raise TensorContractError("; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors())) from None
        a = np.ascontiguousarray(va.array)
        a.setflags(write=False)
        digest = tensor_sha256(a)
        key = f"{spec.name}/{digest[:16]}"
        ref = TensorRef(spec=spec, key=key, shape=tuple(int(n) for n in a.shape), sha256=digest,
                        producer=producer, stats=_stats(a))
        self._arrays[key] = a
        self._refs[key] = ref
        return ref

    def get(self, ref: TensorRef, verify: bool = True) -> np.ndarray:
        a = self._arrays.get(ref.key)
        if a is None:
            raise KeyError(f"unknown tensor key {ref.key}")
        if verify and tensor_sha256(a) != ref.sha256:
            raise TensorContractError(f"{ref.key}: checksum mismatch")
        return a

    def save_npz(self, refs: Mapping[str, TensorRef], path: str) -> None:
        np.savez_compressed(path, **{name: self.get(ref) for name, ref in refs.items() if ref is not None})

    # TensorStorePort -------------------------------------------------------
    def describe(self, key: str) -> TensorRef:
        return self._refs[key]

    def contains(self, ref: TensorRef) -> bool:
        return self._refs.get(ref.key) == ref

    def release(self, key: str) -> None:
        self._arrays.pop(key, None)
        self._refs.pop(key, None)

    def __len__(self) -> int:
        return len(self._arrays)
