import doctest
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError  # noqa: E402

from app.application.common import ABSENCE_STATES  # noqa: E402
from app.application.evaluation import (  # noqa: E402
    CONTRACTS, SCHEMA_VERSION, AbsenceJudgment, AbsencePrediction, EdgeJudgment, EdgePrediction,
    EvaluationEnvelope, RankedRun, RelevanceJudgment, absence_metrics, edge_metrics, evaluate, mrr, ndcg_at_k,
    recall_at_k,
)

SYS = "hybrid-synthetic"
H = "0" * 64


def env(**kw):
    base = dict(judgment_set_id="synthetic-set", judgment_set_sha256=H, system_id=SYS, system_version="0.0.1",
                config_sha256=H, run_id="run-1", criteria_frozen_before_run=True)
    base.update(kw)
    return EvaluationEnvelope(**base)


def rj(q, i, g):
    return RelevanceJudgment(query_id=q, item_id=i, grade=g)


def run(q, *items, system=SYS):
    return RankedRun(system_id=system, query_id=q, items=items)


# Synthetic fixture: q1 has two relevant docs, q2 one, q3 none (excluded from scoring).
REL = [rj("q1", "d1", 3), rj("q1", "d2", 1), rj("q1", "d9", 0), rj("q2", "d5", 2), rj("q3", "d7", 0)]
RUNS = [run("q1", "d9", "d1", "d3", "d2"), run("q2", "d5"), run("q3", "d7")]


class Retrieval(unittest.TestCase):
    def test_recall_at_k(self):
        self.assertAlmostEqual(recall_at_k(REL, RUNS, 2), 0.75)
        self.assertAlmostEqual(recall_at_k(REL, RUNS, 4), 1.0)

    def test_mrr(self):
        self.assertAlmostEqual(mrr(REL, RUNS), (0.5 + 1.0) / 2)

    def test_ndcg_perfect_and_imperfect(self):
        perfect = [run("q1", "d1", "d2"), run("q2", "d5")]
        self.assertAlmostEqual(ndcg_at_k(REL, perfect, 2), 1.0)
        self.assertLess(ndcg_at_k(REL, RUNS, 2), 1.0)

    def test_several_k_in_one_report(self):
        r = evaluate(env(), k_values=(4, 2), relevance=REL, runs=RUNS)
        self.assertEqual(list(r.retrieval.recall_at), [2, 4])
        self.assertAlmostEqual(r.retrieval.recall_at[2], 0.75)
        self.assertAlmostEqual(r.retrieval.recall_at[4], 1.0)

    def test_missing_run_scores_zero_and_is_reported(self):
        r = evaluate(env(), k_values=(2,), relevance=REL, runs=[run("q2", "d5")])
        self.assertAlmostEqual(r.retrieval.recall_at[2], 0.5)
        self.assertEqual(r.coverage.queries_missing_run, 1)

    def test_queries_without_relevant_are_excluded_not_zero(self):
        r = evaluate(env(), relevance=REL, runs=RUNS)
        self.assertEqual((r.coverage.queries_scored, r.coverage.queries_without_relevant), (2, 1))

    def test_no_judgments_omits_metric(self):
        r = evaluate(env(), runs=RUNS)
        self.assertEqual(r.retrieval.recall_at, {})
        self.assertIsNone(r.retrieval.mrr)
        self.assertIsNone(r.edges)
        self.assertIsNone(r.absence)

    def test_conflicting_judgments_rejected(self):
        with self.assertRaises(ValueError):
            recall_at_k([rj("q1", "d1", 1), rj("q1", "d1", 2)], RUNS, 1)

    def test_one_system_at_a_time(self):
        with self.assertRaises(ValueError):
            evaluate(env(), relevance=REL, runs=[run("q1", "d1", system="other")])

    def test_ranked_items_unique(self):
        with self.assertRaises(ValidationError):
            run("q1", "d1", "d1")

    def test_k_must_be_positive(self):
        with self.assertRaises(ValueError):
            evaluate(env(), k_values=(0,), relevance=REL, runs=RUNS)


class Envelope(unittest.TestCase):
    def test_hashes_must_be_sha256(self):
        with self.assertRaises(ValidationError):
            env(config_sha256="abc")

    def test_envelope_is_required(self):
        r = evaluate(env(scope="partition-a"), relevance=REL, runs=RUNS)
        self.assertEqual(r.envelope.scope, "partition-a")
        self.assertTrue(r.envelope.criteria_frozen_before_run)


class Edges(unittest.TestCase):
    LABELS = [
        EdgeJudgment(source_id="a", relation="revision_of", target_id="b", label="true"),
        EdgeJudgment(source_id="a", relation="supersedes", target_id="c", label="false"),
        EdgeJudgment(source_id="x", relation="document_of", target_id="p", label="true"),
        EdgeJudgment(source_id="y", relation="document_of", target_id="p", label="unknown"),
    ]
    PREDS = [EdgePrediction(source_id="a", relation="revision_of", target_id="b"),
             EdgePrediction(source_id="a", relation="supersedes", target_id="c"),
             EdgePrediction(source_id="y", relation="document_of", target_id="p"),
             EdgePrediction(source_id="z", relation="document_of", target_id="p")]

    def test_open_world_precision(self):
        o = edge_metrics(self.LABELS, self.PREDS).overall
        self.assertAlmostEqual(o.precision, 0.5)
        self.assertAlmostEqual(o.recall, 0.5)
        self.assertEqual((o.unknown, o.unjudged), (1, 1))

    def test_per_relation_breakdown(self):
        m = edge_metrics(self.LABELS, self.PREDS).by_relation
        self.assertEqual(set(m), {"revision_of", "supersedes", "document_of"})
        self.assertEqual(m["revision_of"].precision, 1.0)
        self.assertEqual(m["supersedes"].precision, 0.0)
        self.assertIsNone(m["document_of"].precision)
        self.assertEqual(m["document_of"].recall, 0.0)

    def test_relation_type_matters(self):
        o = edge_metrics(self.LABELS, [EdgePrediction(source_id="a", relation="document_of", target_id="b")]).overall
        self.assertIsNone(o.precision)
        self.assertEqual(o.unjudged, 1)


class Absence(unittest.TestCase):
    def test_states_come_from_common(self):
        self.assertEqual(set(ABSENCE_STATES), {"confirmed", "candidate", "superseded", "not_yet_due",
                                               "inaccessible", "not_found_in_scope", "not_applicable"})

    def test_accuracy_and_confusion(self):
        truth = [AbsenceJudgment(expected_node_id="e1", state="confirmed"),
                 AbsenceJudgment(expected_node_id="e2", state="inaccessible"),
                 AbsenceJudgment(expected_node_id="e3", state="superseded")]
        pred = [AbsencePrediction(expected_node_id="e1", state="confirmed"),
                AbsencePrediction(expected_node_id="e2", state="not_found_in_scope"),
                AbsencePrediction(expected_node_id="e9", state="candidate")]
        m = absence_metrics(truth, pred)
        self.assertAlmostEqual(m.accuracy, 1 / 3)
        self.assertEqual(m.confusion["inaccessible"]["not_found_in_scope"], 1)
        self.assertEqual(m.confusion["superseded"]["missing_prediction"], 1)
        self.assertEqual(m.predictions_unjudged, 1)

    def test_unknown_state_rejected(self):
        with self.assertRaises(ValidationError):
            AbsenceJudgment(expected_node_id="e1", state="missing")


class Report(unittest.TestCase):
    def test_full_report_is_deterministic(self):
        a = evaluate(env(), k_values=(2, 5), relevance=REL, runs=RUNS)
        b = evaluate(env(), k_values=(5, 2), relevance=list(reversed(REL)), runs=list(reversed(RUNS)))
        self.assertEqual(a, b)
        self.assertEqual(a.schema_version, SCHEMA_VERSION)
        self.assertTrue(all(math.isfinite(v) for v in a.retrieval.recall_at.values()))

    def test_report_is_frozen(self):
        r = evaluate(env(), relevance=REL, runs=RUNS)
        with self.assertRaises(ValidationError):
            r.coverage = None


class DocsFirst(unittest.TestCase):
    def test_every_field_has_a_description(self):
        for m in CONTRACTS:
            for name, f in m.model_fields.items():
                self.assertTrue(f.description, f"{m.__name__}.{name}")

    def test_design_page_examples_run(self):
        page = ROOT / "docs" / "architecture" / "EVALUATION.md"
        result = doctest.testfile(str(page), module_relative=False, verbose=False)
        self.assertEqual(result.failed, 0)
        self.assertGreater(result.attempted, 0)


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
