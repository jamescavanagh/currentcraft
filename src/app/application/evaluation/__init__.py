"""Evaluation harness (0.11.0): retrieval, edge and absence-state metrics over labeled judgments."""
from .contracts import (  # noqa: F401
    ABSENCE_STATES,
    EVALUATION_SCHEMA,
    AbsenceJudgment,
    AbsencePrediction,
    EdgeJudgment,
    EdgePrediction,
    EvaluationReport,
    RankedRun,
    RelevanceJudgment,
)
from .metrics import absence_accuracy, edge_scores, evaluate, mrr, ndcg_at_k, recall_at_k  # noqa: F401
