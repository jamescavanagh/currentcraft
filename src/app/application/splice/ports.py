"""Splice port. No arrays in signatures: the kernel returns Pydantic records."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import PhaseAssignment, SpliceRequest, SpliceResult


@runtime_checkable
class SpliceKernelPort(Protocol):
    def encode(self, request: SpliceRequest, assignments: tuple[PhaseAssignment, ...]) -> SpliceResult:
        """Hash, phase-block and couple the non-excluded objects. assignments align with them, in input order."""
        ...
