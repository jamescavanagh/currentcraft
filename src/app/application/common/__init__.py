"""Neutral shared contract bases. Every application slice may import from here; nothing here imports a slice."""
from .contracts import _Frozen  # noqa: F401
from .states import ABSENCE_STATES, AbsenceState  # noqa: F401
