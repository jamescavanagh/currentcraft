"""Shared state vocabularies used by more than one slice. Imports nothing from any slice."""
from __future__ import annotations

from typing import Literal, get_args

AbsenceState = Literal[
    "confirmed", "candidate", "superseded", "not_yet_due", "inaccessible", "not_found_in_scope", "not_applicable",
]
"""Resolution of an expected node (docs/domain/DOCUMENT_LIFECYCLE.md, absence states).

``not_found_in_scope`` means not found within the searched and accessible scope, never "does not exist";
``inaccessible`` means the source exists or may exist but could not be read.
"""

ABSENCE_STATES: tuple[str, ...] = get_args(AbsenceState)
