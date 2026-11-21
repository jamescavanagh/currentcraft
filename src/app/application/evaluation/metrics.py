"""Deterministic metric functions (design: docs/architecture/EVALUATION.md). Pure Python."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Optional

from .contracts import (
    ABSENCE_STATES,
    AbsenceJudgment,
    AbsenceMetrics,
    AbsencePrediction,
    Coverage,
    EdgeJudgment,
    EdgeMetrics,
    EdgePrediction,
    EvaluationEnvelope,
    EvaluationReport,
    RankedRun,
    RelationEdgeMetrics,
    RelevanceJudgment,
    RetrievalMetrics,
)


def _grades(judgments: Iterable[RelevanceJudgment]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for j in judgments:
        if j.item_id in out[j.query_id] and out[j.query_id][j.item_id] != j.grade:
            raise ValueError(f"conflicting judgments for {j.query_id}/{j.item_id}")
        out[j.query_id][j.item_id] = j.grade
    return dict(out)


def _runs_by_query(runs: Iterable[RankedRun]) -> dict[str, RankedRun]:
    out: dict[str, RankedRun] = {}
    systems = set()
    for r in runs:
        systems.add(r.system_id)
        if r.query_id in out:
            raise ValueError(f"duplicate run for query {r.query_id}")
        out[r.query_id] = r
    if len(systems) > 1:
        raise ValueError("evaluate one system at a time")
    return out


def _scored_queries(grades: dict[str, dict[str, int]]) -> list[str]:
    """Queries with at least one relevant item, sorted for determinism."""
    return sorted(q for q, g in grades.items() if any(v > 0 for v in g.values()))


def recall_at_k(judgments, runs, k: int) -> Optional[float]:
    grades, by_q = _grades(judgments), _runs_by_query(runs)
    qs = _scored_queries(grades)
    if not qs:
        return None
    total = 0.0
    for q in qs:
        rel = {i for i, g in grades[q].items() if g > 0}
        top = by_q[q].items[:k] if q in by_q else ()
        total += len(rel.intersection(top)) / len(rel)
    return total / len(qs)


def mrr(judgments, runs) -> Optional[float]:
    grades, by_q = _grades(judgments), _runs_by_query(runs)
    qs = _scored_queries(grades)
    if not qs:
        return None
    total = 0.0
    for q in qs:
        items = by_q[q].items if q in by_q else ()
        for rank, item in enumerate(items, start=1):
            if grades[q].get(item, 0) > 0:
                total += 1.0 / rank
                break
    return total / len(qs)


def ndcg_at_k(judgments, runs, k: int) -> Optional[float]:
    grades, by_q = _grades(judgments), _runs_by_query(runs)
    qs = _scored_queries(grades)
    if not qs:
        return None

    def dcg(gs):
        return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gs))

    total = 0.0
    for q in qs:
        items = by_q[q].items[:k] if q in by_q else ()
        got = dcg([grades[q].get(i, 0) for i in items])
        ideal = dcg(sorted(grades[q].values(), reverse=True)[:k])
        total += got / ideal if ideal else 0.0
    return total / len(qs)


def _edge_block(labels: dict, preds: set) -> RelationEdgeMetrics:
    judged = [p for p in preds if labels.get(p) in ("true", "false")]
    tp = sum(1 for p in judged if labels[p] == "true")
    true_edges = {k for k, v in labels.items() if v == "true"}
    return RelationEdgeMetrics(
        precision=tp / len(judged) if judged else None,
        recall=len(true_edges & preds) / len(true_edges) if true_edges else None,
        predicted=len(preds), judged=len(judged),
        unknown=sum(1 for p in preds if labels.get(p) == "unknown"),
        unjudged=sum(1 for p in preds if p not in labels),
    )


def edge_metrics(judgments: Iterable[EdgeJudgment], predictions: Iterable[EdgePrediction]) -> EdgeMetrics:
    """Open-world edge metrics overall and per relation type."""
    labels: dict[tuple[str, str, str], str] = {}
    for j in judgments:
        key = (j.source_id, j.relation, j.target_id)
        if key in labels and labels[key] != j.label:
            raise ValueError(f"conflicting edge labels for {key}")
        labels[key] = j.label
    preds = {(p.source_id, p.relation, p.target_id) for p in predictions}
    relations = sorted({k[1] for k in labels} | {p[1] for p in preds})
    by_relation = {r: _edge_block({k: v for k, v in labels.items() if k[1] == r}, {p for p in preds if p[1] == r})
                   for r in relations}
    return EdgeMetrics(overall=_edge_block(labels, preds), by_relation=by_relation)


def absence_metrics(judgments: Iterable[AbsenceJudgment], predictions: Iterable[AbsencePrediction]) -> AbsenceMetrics:
    """Accuracy over judged expected nodes plus a full confusion matrix.

    A judged node with no prediction counts as wrong and is reported as ``missing_prediction``.
    """
    truth: dict[str, str] = {}
    for j in judgments:
        if j.expected_node_id in truth and truth[j.expected_node_id] != j.state:
            raise ValueError(f"conflicting absence labels for {j.expected_node_id}")
        truth[j.expected_node_id] = j.state
    pred: dict[str, str] = {}
    for p in predictions:
        if p.expected_node_id in pred and pred[p.expected_node_id] != p.state:
            raise ValueError(f"conflicting predictions for {p.expected_node_id}")
        pred[p.expected_node_id] = p.state
    confusion = {t: {s: 0 for s in ABSENCE_STATES + ("missing_prediction",)} for t in ABSENCE_STATES}
    correct = 0
    for node, t in sorted(truth.items()):
        p = pred.get(node, "missing_prediction")
        confusion[t][p] += 1
        correct += p == t
    return AbsenceMetrics(accuracy=correct / len(truth) if truth else None,
                          confusion=confusion if truth else {}, judged=len(truth),
                          predictions_unjudged=sum(1 for n in pred if n not in truth))


def evaluate(envelope: EvaluationEnvelope, *, k_values: tuple[int, ...] = (10,), relevance=(), runs=(),
             edge_labels=None, edges=None, absence_labels=None, absence_predictions=None) -> EvaluationReport:
    """One report for one system. Metrics with no judged population are omitted, never zero-filled."""
    if not k_values or any(k < 1 for k in k_values):
        raise ValueError("k_values must be positive")
    relevance, runs = list(relevance), list(runs)
    for r in runs:
        if r.system_id != envelope.system_id:
            raise ValueError(f"run from {r.system_id} passed to evaluation of {envelope.system_id}")
    grades = _grades(relevance)
    scored = _scored_queries(grades)
    by_q = _runs_by_query(runs)
    ks = tuple(sorted(set(k_values)))
    recall = {k: v for k in ks if (v := recall_at_k(relevance, runs, k)) is not None}
    ndcg = {k: v for k in ks if (v := ndcg_at_k(relevance, runs, k)) is not None}
    retrieval = RetrievalMetrics(recall_at=recall, ndcg_at=ndcg, mrr=mrr(relevance, runs))
    edges_out = None if edge_labels is None and edges is None else edge_metrics(edge_labels or (), edges or ())
    absence_out = (None if absence_labels is None and absence_predictions is None
                   else absence_metrics(absence_labels or (), absence_predictions or ()))
    coverage = Coverage(queries_judged=len(grades), queries_scored=len(scored),
                        queries_without_relevant=len(grades) - len(scored),
                        queries_missing_run=sum(1 for q in scored if q not in by_q))
    return EvaluationReport(envelope=envelope, retrieval=retrieval, edges=edges_out, absence=absence_out,
                            coverage=coverage)
