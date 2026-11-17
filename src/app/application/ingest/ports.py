"""Ingestion ports. No bytes or arrays in signatures except the blob store's own put/get."""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from .contracts import AdapterResult, FrozenProjection, IngestConfig, JsonMapping, RawItem, RingEntry, TensorBatch, TensorPlan, DomainObject


@runtime_checkable
class BlobStorePort(Protocol):
    def contains(self, key: str, sha256: str) -> bool: ...


@runtime_checkable
class SourceAdapterPort(Protocol):
    name: str
    version: str

    def parse(self, raw: RawItem, config: IngestConfig, mappings: Mapping[str, JsonMapping]) -> AdapterResult: ...


@runtime_checkable
class TensorizerPort(Protocol):
    def build(self, consumer: str, plan: TensorPlan, entries: tuple[RingEntry, ...]) -> TensorBatch: ...

    def fit_projection(self, name: str, text_dim: int, objects: tuple[DomainObject, ...]) -> FrozenProjection: ...
