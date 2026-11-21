"""Evaluation contracts. Judgments come from people; runs and predictions come from systems.

Open-world rule: an unjudged prediction is *unknown*, never counted as wrong. Every report states its
coverage so a high score on a small judged slice is visible as such.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.application.common import _Frozen

EVALUATION_SCHEMA = "currentcraft-evaluation/v1"

AbsenceState = Literal[
    "confirmed", "candidate", "superseded", "not_yet_due", "inaccessible", "not_found_in_scope", "not_applicable",
]
ABSENCE_STATES: tuple[str, ...] = AbsenceState.__args__  # type: ignore[attr-defined]

_Id = Field(min_length=1, max_length=200)


class RelevanceJudgment(_Frozen):
    """Graded relevance of one item for one query. Grade 0 is judged not relevant."""

    query_id: str = _Id
    item_id: str = _Id
    grade: int = Field(ge=0, le=3)


class RankedRun(_Frozen):
    """One system's ranked results for one query, best first."""

    system_id: str = _Id
    query_id: str = _Id
    items: tuple[str, ...]

    @model_validator(mode="after")
    def _unique(self):
        if len(set(self.items)) != len(self.items):
            raise ValueError("ranked items must be unique")
        if any(not i for i in self.items):
            raise ValueError("item ids must be non-empty")
        return self


class EdgeJudgment(_Frozen):
    """Human label for a typed edge. ``unknown`` is allowed and excluded from precision."""

    source_id: str = _Id
    relation: str = _Id
    target_id: str = _Id
    label: Literal["true", "false", "unknown"]


class EdgePrediction(_Frozen):
    source_id: str = _Id
    relation: str = _Id
    target_id: str = _Id


class AbsenceJudgment(_Frozen):
    expected_node_id: str = _Id
    state: AbsenceState


class AbsencePrediction(_Frozen):
    expected_node_id: str = _Id
    state: AbsenceState


class EvaluationReport(_Frozen):
    """Metric values plus the coverage needed to interpret them."""

    schema_version: Literal["currentcraft-evaluation/v1"] = EVALUATION_SCHEMA
    system_id: str = _Id
    k: int = Field(ge=1)
    metrics: dict[str, float]
    coverage: dict[str, int]
    absence_confusion: dict[str, dict[str, int]] = Field(default_factory=dict)
