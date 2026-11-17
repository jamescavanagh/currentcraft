"""Plate ports. No signature mentions an array type."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import ArcBoundResult, PlateFieldRequest, PlateFieldResult, PlateRunRequest, PlateRunResult, RingWindingRequest


@runtime_checkable
class PlateDynamicsPort(Protocol):
    def run(self, request: PlateRunRequest) -> PlateRunResult: ...


@runtime_checkable
class PlateFieldPort(Protocol):
    def sample(self, request: PlateFieldRequest) -> PlateFieldResult: ...


@runtime_checkable
class ArcBoundPort(Protocol):
    def bound(self, request: RingWindingRequest) -> ArcBoundResult: ...
