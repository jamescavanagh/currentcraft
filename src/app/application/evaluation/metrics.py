"""Deterministic metric functions. Pure Python; no numeric libraries."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Optional

from .contracts import (
    ABSENCE_STATES,
    AbsenceJudgment,
    AbsencePrediction,
    EdgeJudgment,
    EdgePrediction,
    EvaluationReport,
    RankedRun,
    RelevanceJudgment,
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


def edge_scores(judgments: Iterable[EdgeJudgment], predictions: Iterable[EdgePrediction]) -> dict[str, float | int | None]:
    """Precision over judged predictions; recall over edges judged true. Unknown and unjudged are reported."""
    labels: dict[tuple[str, str, str], str] = {}
    for j in judgments:
        key = (j.source_id, j.relation, j.target_id)
        if key in labels and labels[key] != j.label:
            raise ValueError(f"conflicting edge labels for {key}")
        labels[key] = j.label
    preds = {(p.source_id, p.relation, p.target_id) for p in predictions}
    judged = [p for p in preds if labels.get(p) in ("true", "false")]
    tp = sum(1 for p in judged if labels[p] == "true")
    true_edges = {k for k, v in labels.items() if v == "true"}
    return {
        "edge_precision": tp / len(judged) if judged else None,
        "edge_recall": len(true_edges & preds) / len(true_edges) if true_edges else None,
        "edges_predicted": len(preds),
        "edges_judged": len(judged),
        "edges_unknown": sum(1 for p in preds if labels.get(p) == "unknown"),
        "edges_unjudged": sum(1 for p in preds if p not in labels),
    }


def absence_accuracy(judgments: Iterable[AbsenceJudgment], predictions: Iterable[AbsencePrediction]):
    """Accuracy over judged expected nodes plus a full confusion matrix (truth -> predicted -> count).

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
    acc = correct / len(truth) if truth else None
    return acc, confusion, {"expected_nodes_judged": len(truth),
                            "predictions_unjudged": sum(1 for n in pred if n not in truth)}


def evaluate(system_id: str, *, k: int = 10, relevance=(), runs=(), edge_labels=(), edges=(),
             absence_labels=(), absence_predictions=()) -> EvaluationReport:
    """One report for one system. Metrics that have no judged population are omitted, never zero-filled."""
    relevance, runs = list(relevance), list(runs)
    for r in runs:
        if r.system_id != system_id:
            raise ValueError(f"run from {r.system_id} passed to evaluation of {system_id}")
    metrics: dict[str, float] = {}
    coverage: dict[str, int] = {}
    grades = _grades(relevance)
    scored = _scored_queries(grades)
    by_q = _runs_by_query(runs)
    coverage["queries_judged"] = len(grades)
    coverage["queries_scored"] = len(scored)
    coverage["queries_without_relevant"] = len(grades) - len(scored)
    coverage["queries_missing_run"] = sum(1 for q in scored if q not in by_q)
    for name, value in (("recall_at_k", recall_at_k(relevance, runs, k)), ("mrr", mrr(relevance, runs)),
                        ("ndcg_at_k", ndcg_at_k(relevance, runs, k))):
        if value is not None:
            metrics[name] = value
    es = edge_scores(edge_labels, edges)
    for key in ("edge_precision", "edge_recall"):
        if es[key] is not None:
            metrics[key] = es[key]
    for key in ("edges_predicted", "edges_judged", "edges_unknown", "edges_unjudged"):
        coverage[key] = es[key]
    acc, confusion, acov = absence_accuracy(absence_labels, absence_predictions)
    if acc is not None:
        metrics["absence_accuracy"] = acc
    coverage.update(acov)
    return EvaluationReport(system_id=system_id, k=k, metrics=metrics, coverage=coverage,
                            absence_confusion=confusion if acov["expected_nodes_judged"] else {})
