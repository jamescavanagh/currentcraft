"""Shared Pydantic base for frozen, closed contracts (0.9.9: moved out of simulation.contracts).

``simulation.contracts`` re-exports ``_Frozen`` for one release so external imports keep working.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    """Immutable, closed model: unknown fields are rejected, instances are hashable values."""

    model_config = ConfigDict(frozen=True, extra="forbid")
