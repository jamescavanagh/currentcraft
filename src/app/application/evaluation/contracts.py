"""Evaluation contracts (design: docs/architecture/EVALUATION.md).

Judgments come from people; runs and predictions come from systems. Open-world rule: an unjudged
prediction is *unknown*, never counted as wrong. Every report carries its evidence envelope and its
coverage, so a high score on a small judged slice is visible as such.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, model_validator

from app.application.common import ABSENCE_STATES, AbsenceState, _Frozen

SCHEMA_VERSION = "currentcraft-evaluation/v1"
EVALUATION_SCHEMA = SCHEMA_VERSION  # alias kept for callers of the first draft

_SHA = r"^[0-9a-f]{64}$"


def _id(description: str):
    return Field(min_length=1, max_length=200, description=description)


class RelevanceJudgment(_Frozen):
    """Graded relevance of one item for one query, recorded by a person. Grade 0 is judged not relevant."""

    query_id: str = _id("Query identifier within the judgment set.")
    item_id: str = _id("Opaque item identifier (chunk, page or document handle).")
    grade: int = Field(ge=0, le=3, description="0 not relevant, 1 partial, 2 relevant, 3 exact answer.")


class RankedRun(_Frozen):
    """One system's ranked results for one query, best first."""

    system_id: str = _id("System under evaluation; one report covers one system.")
    query_id: str = _id("Query identifier matching the judgment set.")
    items: tuple[str, ...] = Field(description="Ranked opaque item identifiers, best first, unique.")

    @model_validator(mode="after")
    def _unique(self):
        if len(set(self.items)) != len(self.items):
            raise ValueError("ranked items must be unique")
        if any(not i for i in self.items):
            raise ValueError("item ids must be non-empty")
        return self


class EdgeJudgment(_Frozen):
    """Human label for one typed edge. ``unknown`` is allowed and excluded from precision."""

    source_id: str = _id("Opaque source node identifier.")
    relation: str = _id("Relation type, e.g. revision_of.")
    target_id: str = _id("Opaque target node identifier.")
    label: Literal["true", "false", "unknown"] = Field(description="Human label; unknown is not false.")


class EdgePrediction(_Frozen):
    """One typed edge proposed by a system. A prediction is a candidate, never a confirmed relation."""

    source_id: str = _id("Opaque source node identifier.")
    relation: str = _id("Relation type, e.g. revision_of.")
    target_id: str = _id("Opaque target node identifier.")


class AbsenceJudgment(_Frozen):
    """Human label for how an expected node resolves."""

    expected_node_id: str = _id("Opaque identifier of the expected node.")
    state: AbsenceState = Field(description="One of the absence states in docs/domain/DOCUMENT_LIFECYCLE.md.")


class AbsencePrediction(_Frozen):
    """A system's resolution of an expected node."""

    expected_node_id: str = _id("Opaque identifier of the expected node.")
    state: AbsenceState = Field(description="One of the absence states in docs/domain/DOCUMENT_LIFECYCLE.md.")


class EvaluationEnvelope(_Frozen):
    """Where a report came from (evidence envelope): judgments, system, configuration and run."""

    judgment_set_id: str = _id("Identifier of the judgment set; real sets live in private references.")
    judgment_set_sha256: str = Field(pattern=_SHA, description="SHA-256 of the serialized judgment set.")
    system_id: str = _id("System under evaluation.")
    system_version: str = _id("Version of the system, model or index that produced the runs.")
    config_sha256: str = Field(pattern=_SHA, description="SHA-256 of the retrieval or prediction configuration.")
    run_id: str = _id("Reproducible run reference.")
    scope: Optional[str] = Field(default=None, min_length=1, max_length=200,
                                 description="Optional filter scope label, e.g. an opaque project partition.")
    criteria_frozen_before_run: bool = Field(
        description="True only if pass criteria were recorded before the run; held-out claims require it.")


class RetrievalMetrics(_Frozen):
    """Ranking quality over queries that have at least one relevant judgment."""

    recall_at: dict[int, float] = Field(default_factory=dict, description="Recall@k keyed by k.")
    ndcg_at: dict[int, float] = Field(default_factory=dict, description="nDCG@k keyed by k.")
    mrr: Optional[float] = Field(default=None, ge=0, le=1, description="Mean reciprocal rank; None when nothing is scored.")


class RelationEdgeMetrics(_Frozen):
    """Open-world edge quality for one relation type, or for all relations."""

    precision: Optional[float] = Field(default=None, ge=0, le=1, description="True over judged predictions; None when none judged.")
    recall: Optional[float] = Field(default=None, ge=0, le=1, description="Predicted over edges judged true; None when none judged true.")
    predicted: int = Field(ge=0, description="Distinct predicted edges.")
    judged: int = Field(ge=0, description="Predicted edges with a true or false label.")
    unknown: int = Field(ge=0, description="Predicted edges labelled unknown.")
    unjudged: int = Field(ge=0, description="Predicted edges with no label at all.")


class EdgeMetrics(_Frozen):
    """Edge quality overall and per relation type (per-relation calibration needs the breakdown)."""

    overall: RelationEdgeMetrics = Field(description="All relation types together.")
    by_relation: dict[str, RelationEdgeMetrics] = Field(default_factory=dict, description="Keyed by relation type.")


class AbsenceMetrics(_Frozen):
    """Absence-state accuracy and its confusion matrix (truth -> predicted -> count)."""

    accuracy: Optional[float] = Field(default=None, ge=0, le=1, description="Correct over judged expected nodes.")
    confusion: dict[str, dict[str, int]] = Field(
        default_factory=dict, description="Truth state -> predicted state (or missing_prediction) -> count.")
    judged: int = Field(ge=0, description="Expected nodes with a human label.")
    predictions_unjudged: int = Field(ge=0, description="Predictions for nodes nobody labelled.")


class Coverage(_Frozen):
    """Population counts needed to interpret every metric."""

    queries_judged: int = Field(ge=0, description="Queries with any judgment.")
    queries_scored: int = Field(ge=0, description="Queries with at least one relevant item.")
    queries_without_relevant: int = Field(ge=0, description="Judged queries excluded because nothing is relevant.")
    queries_missing_run: int = Field(ge=0, description="Scored queries the system returned no run for (scored as zero).")


class EvaluationReport(_Frozen):
    """One system's evaluation: envelope, typed metrics and coverage. Never an approval or a relation."""

    schema_version: Literal["currentcraft-evaluation/v1"] = Field(default=SCHEMA_VERSION, description="Payload schema.")
    envelope: EvaluationEnvelope = Field(description="Evidence envelope for this report.")
    retrieval: RetrievalMetrics = Field(description="Ranking metrics; empty when no relevance judgments.")
    edges: Optional[EdgeMetrics] = Field(default=None, description="Edge metrics; None when no edges were evaluated.")
    absence: Optional[AbsenceMetrics] = Field(default=None, description="Absence metrics; None when no labels.")
    coverage: Coverage = Field(description="Population counts for interpreting the metrics.")


CONTRACTS = (RelevanceJudgment, RankedRun, EdgeJudgment, EdgePrediction, AbsenceJudgment, AbsencePrediction,
             EvaluationEnvelope, RetrievalMetrics, RelationEdgeMetrics, EdgeMetrics, AbsenceMetrics, Coverage,
             EvaluationReport)

__all__ = ["ABSENCE_STATES", "AbsenceState", "CONTRACTS", "EVALUATION_SCHEMA", "SCHEMA_VERSION",
           *[c.__name__ for c in CONTRACTS]]
