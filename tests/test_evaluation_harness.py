import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError  # noqa: E402

from app.application.evaluation import (  # noqa: E402
    ABSENCE_STATES, EVALUATION_SCHEMA, AbsenceJudgment, AbsencePrediction, EdgeJudgment, EdgePrediction,
    RankedRun, RelevanceJudgment, absence_accuracy, edge_scores, evaluate, mrr, ndcg_at_k, recall_at_k,
)

SYS = "hybrid-synthetic"


def rj(q, i, g):
    return RelevanceJudgment(query_id=q, item_id=i, grade=g)


def run(q, *items, system=SYS):
    return RankedRun(system_id=system, query_id=q, items=items)


# Synthetic fixture: q1 has two relevant docs, q2 one, q3 none (excluded from scoring).
REL = [rj("q1", "d1", 3), rj("q1", "d2", 1), rj("q1", "d9", 0), rj("q2", "d5", 2), rj("q3", "d7", 0)]
RUNS = [run("q1", "d9", "d1", "d3", "d2"), run("q2", "d5"), run("q3", "d7")]


class Retrieval(unittest.TestCase):
    def test_recall_at_k(self):
        # q1: top2 = d9,d1 -> 1/2; q2: 1/1 -> mean 0.75
        self.assertAlmostEqual(recall_at_k(REL, RUNS, 2), 0.75)
        self.assertAlmostEqual(recall_at_k(REL, RUNS, 4), 1.0)

    def test_mrr(self):
        # q1 first relevant at rank 2, q2 at rank 1
        self.assertAlmostEqual(mrr(REL, RUNS), (0.5 + 1.0) / 2)

    def test_ndcg_perfect_and_imperfect(self):
        perfect = [run("q1", "d1", "d2"), run("q2", "d5")]
        self.assertAlmostEqual(ndcg_at_k(REL, perfect, 2), 1.0)
        self.assertLess(ndcg_at_k(REL, RUNS, 2), 1.0)

    def test_missing_run_scores_zero_and_is_reported(self):
        report = evaluate(SYS, k=2, relevance=REL, runs=[run("q2", "d5")])
        self.assertAlmostEqual(report.metrics["recall_at_k"], 0.5)
        self.assertEqual(report.coverage["queries_missing_run"], 1)

    def test_queries_without_relevant_are_excluded_not_zero(self):
        report = evaluate(SYS, k=2, relevance=REL, runs=RUNS)
        self.assertEqual(report.coverage["queries_scored"], 2)
        self.assertEqual(report.coverage["queries_without_relevant"], 1)

    def test_no_judgments_omits_metric(self):
        self.assertIsNone(recall_at_k([], RUNS, 5))
        self.assertNotIn("recall_at_k", evaluate(SYS, runs=RUNS).metrics)

    def test_conflicting_judgments_rejected(self):
        with self.assertRaises(ValueError):
            recall_at_k([rj("q1", "d1", 1), rj("q1", "d1", 2)], RUNS, 1)

    def test_one_system_at_a_time(self):
        with self.assertRaises(ValueError):
            evaluate(SYS, relevance=REL, runs=[run("q1", "d1", system="other")])

    def test_ranked_items_unique(self):
        with self.assertRaises(ValidationError):
            run("q1", "d1", "d1")


class Edges(unittest.TestCase):
    LABELS = [
        EdgeJudgment(source_id="a", relation="revision_of", target_id="b", label="true"),
        EdgeJudgment(source_id="a", relation="supersedes", target_id="c", label="false"),
        EdgeJudgment(source_id="x", relation="document_of", target_id="p", label="true"),
        EdgeJudgment(source_id="y", relation="document_of", target_id="p", label="unknown"),
    ]

    def test_open_world_precision(self):
        preds = [EdgePrediction(source_id="a", relation="revision_of", target_id="b"),
                 EdgePrediction(source_id="a", relation="supersedes", target_id="c"),
                 EdgePrediction(source_id="y", relation="document_of", target_id="p"),
                 EdgePrediction(source_id="z", relation="document_of", target_id="p")]
        s = edge_scores(self.LABELS, preds)
        self.assertAlmostEqual(s["edge_precision"], 0.5)  # unknown and unjudged excluded
        self.assertAlmostEqual(s["edge_recall"], 0.5)
        self.assertEqual((s["edges_unknown"], s["edges_unjudged"]), (1, 1))

    def test_relation_type_matters(self):
        s = edge_scores(self.LABELS, [EdgePrediction(source_id="a", relation="document_of", target_id="b")])
        self.assertIsNone(s["edge_precision"])
        self.assertEqual(s["edges_unjudged"], 1)


class Absence(unittest.TestCase):
    def test_states_match_decision_record(self):
        self.assertEqual(set(ABSENCE_STATES), {"confirmed", "candidate", "superseded", "not_yet_due",
                                               "inaccessible", "not_found_in_scope", "not_applicable"})

    def test_accuracy_and_confusion(self):
        truth = [AbsenceJudgment(expected_node_id="e1", state="confirmed"),
                 AbsenceJudgment(expected_node_id="e2", state="inaccessible"),
                 AbsenceJudgment(expected_node_id="e3", state="superseded")]
        pred = [AbsencePrediction(expected_node_id="e1", state="confirmed"),
                AbsencePrediction(expected_node_id="e2", state="not_found_in_scope"),
                AbsencePrediction(expected_node_id="e9", state="candidate")]
        acc, confusion, cov = absence_accuracy(truth, pred)
        self.assertAlmostEqual(acc, 1 / 3)
        # inaccessible mislabelled as not found is the failure this metric exists to expose
        self.assertEqual(confusion["inaccessible"]["not_found_in_scope"], 1)
        self.assertEqual(confusion["superseded"]["missing_prediction"], 1)
        self.assertEqual(cov["predictions_unjudged"], 1)

    def test_unknown_state_rejected(self):
        with self.assertRaises(ValidationError):
            AbsenceJudgment(expected_node_id="e1", state="missing")


class Report(unittest.TestCase):
    def test_full_report_is_deterministic(self):
        a = evaluate(SYS, k=2, relevance=REL, runs=RUNS)
        b = evaluate(SYS, k=2, relevance=list(reversed(REL)), runs=list(reversed(RUNS)))
        self.assertEqual(a, b)
        self.assertEqual(a.schema_version, EVALUATION_SCHEMA)
        self.assertTrue(all(math.isfinite(v) for v in a.metrics.values()))

    def test_report_is_frozen(self):
        r = evaluate(SYS, relevance=REL, runs=RUNS)
        with self.assertRaises(ValidationError):
            r.k = 5


class Layering(unittest.TestCase):
    def test_slice_is_pure_python_and_imports_only_common(self):
        import ast
        heavy = {"numpy", "torch", "scipy", "pandas", "sklearn"}
        files = sorted((ROOT / "src" / "app" / "application" / "evaluation").glob("*.py"))
        self.assertTrue(files)
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    mods.add(node.module)
            self.assertFalse({m for m in mods if m.split(".")[0] in heavy}, f.name)
            app = {m for m in mods if m.startswith("app.")}
            self.assertFalse(app - {"app.application.common"}, f.name)


if __name__ == "__main__":
    unittest.main()
