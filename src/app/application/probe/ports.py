"""Probe ports. Array-free."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import CandidateRequest, CandidateSet, LensReading, LensRequest, ProbeReading, ProbeRequest


@runtime_checkable
class ProbePort(Protocol):
    def measure(self, request: ProbeRequest) -> ProbeReading: ...


@runtime_checkable
class LensPort(Protocol):
    def lens(self, request: LensRequest) -> LensReading: ...


@runtime_checkable
class CandidatePort(Protocol):
    def cluster(self, request: CandidateRequest) -> CandidateSet: ...
