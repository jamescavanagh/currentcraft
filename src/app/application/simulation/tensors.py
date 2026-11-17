"""Tensor descriptors for the simulation contracts. Pure Python + Pydantic: no numpy here.

Application code never holds arrays. It holds a ``TensorRef``: a validated description
(name, axis names, symbolic shape, dtype, unit) plus the concrete shape and a SHA-256 of
the array bytes held by an infrastructure tensor store. Adapters in
``app.infrastructure.tensors`` turn arrays into refs and back.

>>> spec = TensorSpec(name="field", dims=("slice", "channel", "height", "width"),
...                   shape=("S", 5, "G", "G"), dtype="float32", description="field channels")
>>> spec.symbols
('S', 'G')
>>> spec.bind((16, 5, 32, 32))
{'S': 16, 'G': 32}
>>> spec.bind((16, 5, 32, 31))
Traceback (most recent call last):
...
app.application.simulation.tensors.TensorContractError: field: axis width is 31 but G is already 32
"""

from __future__ import annotations

from typing import Annotated, Iterable, Literal, Mapping, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt, StringConstraints, model_validator

DType = Literal["float32", "float64", "int64", "int32", "int16", "int8", "uint8", "bool"]
Symbol = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Za-z0-9_]*$")]
AxisName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
TensorName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]*$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
TensorKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:/-]{1,200}$")]
DimSize = Union[PositiveInt, Symbol]


class TensorContractError(ValueError):
    """A tensor description or binding is inconsistent with its contract."""


class TensorSpec(BaseModel):
    """What a tensor must look like. Symbols (``N``, ``S``) bind to sizes per contract instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: TensorName = Field(description="Stable tensor name used in docs, stores and keys.")
    dims: tuple[AxisName, ...] = Field(description="Axis names, outermost first.")
    shape: tuple[DimSize, ...] = Field(description="Size per axis: a positive int or a symbol bound per contract.")
    dtype: DType = Field(description="Element type; adapters must not silently cast.")
    unit: Optional[str] = Field(default=None, description="Physical or model unit of the values, if any.")
    layout: Optional[str] = Field(default=None, description="Layout tag such as SCHW, NF or COO.")
    description: str = Field(min_length=1, description="What the values mean.")
    finite: bool = Field(default=True, description="Floating values must be finite (no NaN or inf).")
    min_value: Optional[float] = Field(default=None, description="Inclusive lower bound on values, if any.")
    max_value: Optional[float] = Field(default=None, description="Inclusive upper bound on values, if any.")

    @model_validator(mode="after")
    def _consistent(self) -> "TensorSpec":
        if len(self.dims) != len(self.shape):
            raise ValueError(f"{self.name}: {len(self.dims)} dims but {len(self.shape)} shape entries")
        if len(set(self.dims)) != len(self.dims):
            raise ValueError(f"{self.name}: duplicate axis names")
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError(f"{self.name}: min_value > max_value")
        return self

    @property
    def symbols(self) -> tuple[str, ...]:
        out: list[str] = []
        for s in self.shape:
            if isinstance(s, str) and s not in out:
                out.append(s)
        return tuple(out)

    def bind(self, concrete: Iterable[int], bindings: Optional[Mapping[str, int]] = None) -> dict[str, int]:
        """Check a concrete shape against this spec and return the (extended) symbol bindings."""
        concrete = tuple(int(c) for c in concrete)
        b = dict(bindings or {})
        if len(concrete) != len(self.shape):
            raise TensorContractError(f"{self.name}: rank {len(concrete)} != {len(self.shape)}")
        for axis, want, got in zip(self.dims, self.shape, concrete):
            if isinstance(want, int):
                if got != want:
                    raise TensorContractError(f"{self.name}: axis {axis} is {got}, expected {want}")
            elif want in b and b[want] != got:
                raise TensorContractError(f"{self.name}: axis {axis} is {got} but {want} is already {b[want]}")
            else:
                b[want] = got
        return b


class TensorStats(BaseModel):
    """Cheap summary recorded by the store; lets docs, logs and APIs describe a tensor without its data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min: Optional[float] = Field(default=None, description="Minimum finite value.")
    max: Optional[float] = Field(default=None, description="Maximum finite value.")
    mean: Optional[float] = Field(default=None, description="Mean of finite values.")
    nonfinite: NonNegativeInt = Field(default=0, description="Count of NaN or inf values.")


class TensorRef(BaseModel):
    """A validated handle to a tensor held by an infrastructure store. Carries no array data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: TensorSpec = Field(description="Contract spec the tensor satisfies.")
    key: TensorKey = Field(description="Store key; resolve only through a TensorStorePort.")
    shape: tuple[NonNegativeInt, ...] = Field(description="Concrete shape of the stored array.")
    sha256: Sha256 = Field(description="SHA-256 over dtype, shape and C-order bytes.")
    producer: str = Field(min_length=1, description="Adapter that produced the tensor.")
    stats: Optional[TensorStats] = Field(default=None, description="Summary statistics recorded by the store.")

    @model_validator(mode="after")
    def _shape_matches_spec(self) -> "TensorRef":
        self.spec.bind(self.shape)
        return self


def check_bindings(refs: Mapping[str, Optional[TensorRef]], seed: Optional[Mapping[str, int]] = None) -> dict[str, int]:
    """Symbols must agree across every tensor of one contract instance (and with ``seed`` sizes).

    >>> a = TensorSpec(name="a", dims=("node",), shape=("N",), dtype="float32", description="a")
    >>> ref = TensorRef(spec=a, key="a/1", shape=(3,), sha256="0" * 64, producer="doc")
    >>> check_bindings({"a": ref}, seed={"N": 3})
    {'N': 3}
    """
    b = dict(seed or {})
    for name, ref in refs.items():
        if ref is None:
            continue
        try:
            b = ref.spec.bind(ref.shape, b)
        except TensorContractError as e:
            raise TensorContractError(f"{name}: {e}") from None
    return b
