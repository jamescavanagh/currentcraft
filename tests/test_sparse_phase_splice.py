"""Sparse phase splice: analytic phase controls, evidence rules, sparse layout, persistence and junction semantics."""

import json
import math
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from app.application.ingest.contracts import DomainObject, Provenance, TypedRelation  # noqa: E402
from app.application.splice import (PhaseAnchor, PhaseAssignment, PhaseChart, PhaseEvidenceRule, SpliceProfile,  # noqa: E402
                                    SpliceRequest, assign_phases, store_splice)
from app.infrastructure.ingest.tensorizer import hash_features  # noqa: E402
from app.infrastructure.persistence.vectors import parse_sparse, sparse_literal  # noqa: E402
from app.infrastructure.persistence.wiring import build_memory  # noqa: E402
from app.infrastructure.splice import NumpySpliceKernel, build_splice  # noqa: E402
from app.infrastructure.splice.kernels import content_vector, tokens  # noqa: E402
from tests.test_xlsx_workbook import run, workbook  # noqa: E402

WHEN = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
SIX = ("1", "2", "3", "4", "5", "6")
RULES = (PhaseEvidenceRule(kind="phase_scope", source="field", field="phase_code"),
         PhaseEvidenceRule(kind="wbs_task", source="field", field="phase_code"),
         PhaseEvidenceRule(kind="wbs_row", source="field", field="phase_code"),
         PhaseEvidenceRule(kind="task_role_demand", source="relation", relation_types=("budget_for",)),
         PhaseEvidenceRule(kind="rate_role", source="per_phase_hours", hours_field_template="ph{code}_raw"))


def chart(codes=("1", "2", "3"), **kw):
    kw.setdefault("provenance", "synthetic test chart")
    return PhaseChart.uniform(codes, **kw)


def profile(c=None, **kw):
    return SpliceProfile(name="synthetic-splice", version="1", chart=c or chart(), phase_rules=RULES, **kw)


def obj(oid, kind="wbs_task", title="", text="", fields=None, rels=()):
    return DomainObject(object_id=oid, kind=kind, title=title, text=text, fields=fields or {},
                        relations=tuple(TypedRelation(type=t, target_id=x, evidence="test") for t, x in rels),
                        provenance=Provenance(platform="file", format="xlsx", source_id="s", content_sha256="0" * 64,
                                              adapter="test", adapter_version="0", received_at=WHEN))


def splice(objs, prof=None, **kw):
    return build_splice().splice(SpliceRequest(profile=prof or profile(), objects=tuple(objs), recorded_at=WHEN, **kw))


def dense(rec, dim):
    v = np.zeros(dim)
    v[list(rec.embedding.sparse_indices)] = rec.embedding.sparse_values
    return v


class PhaseChartControls(unittest.TestCase):
    def test_same_phase_couples_fully_and_kappa_zero_ignores_phase(self):
        c = chart(SIX)
        self.assertAlmostEqual(c.coupling("2", "2"), 1.0, places=12)
        flat = chart(SIX, concentration=0.0)
        for a in SIX:
            for b in SIX:
                self.assertAlmostEqual(flat.coupling(a, b), 1.0, places=12)

    def test_shared_weight_one_ignores_phase(self):
        c = chart(SIX, shared_weight=1.0, concentration=30.0)
        self.assertAlmostEqual(c.coupling("1", "4"), 1.0, places=12)

    def test_sharp_chart_with_zero_share_separates_phases(self):
        c = chart(SIX, concentration=64.0, shared_weight=0.0)
        self.assertEqual(c.coupling("1", "2"), 0.0)
        c = chart(SIX, concentration=64.0, shared_weight=0.3)
        self.assertAlmostEqual(c.coupling("1", "4"), 0.3, places=12)

    def test_uniform_spacing_gives_equal_neighbour_coupling(self):
        c = chart(SIX)
        ks = [c.coupling(SIX[i], SIX[(i + 1) % 6]) for i in range(6)]
        for k in ks:
            self.assertAlmostEqual(k, ks[0], places=12)
        self.assertGreater(c.coupling("1", "2"), c.coupling("1", "3"))
        self.assertGreater(c.coupling("1", "3"), c.coupling("1", "4") - 1e-12)

    def test_rotation_by_a_bin_and_mirroring_leave_pairwise_coupling_unchanged(self):
        base = chart(SIX)
        for other in (chart(SIX, origin_deg=30.0), chart(SIX, origin_deg=150.0), chart(SIX, direction="cw")):
            for a in SIX:
                for b in SIX:
                    self.assertAlmostEqual(base.coupling(a, b), other.coupling(a, b), places=12)

    def test_coupling_never_rises_with_concentration_on_bin_centres(self):
        prev = None
        for kappa in (0.0, 0.5, 1, 2, 4, 8, 16, 32):
            k = chart(SIX, concentration=kappa, floor=0.0).coupling("1", "2")
            if prev is not None:
                self.assertLessEqual(k, prev + 1e-12)
            prev = k

    def test_bin_weights_are_a_sparse_distribution(self):
        w = chart(SIX, concentration=4.0, floor=0.05).bin_weights("1")
        self.assertAlmostEqual(sum(w), 1.0, places=12)
        self.assertEqual(sum(1 for x in w if x > 0), 5)
        self.assertIsNone(chart(SIX).bin_weights("9"))

    def test_chart_rules(self):
        with self.assertRaises(ValueError):
            PhaseChart(name="c", version="1", provenance="dup", anchors=(PhaseAnchor(phase_code="1", angle_deg=0),
                                                                          PhaseAnchor(phase_code="1", angle_deg=90)))
        with self.assertRaises(ValueError):
            PhaseChart(name="c", version="1", provenance="x", anchors=(PhaseAnchor(phase_code="1", angle_deg=360),))
        with self.assertRaises(ValueError):
            SpliceProfile(name="p", version="1", text_dim=8192, chart=chart(bins=12))

    def test_any_parameter_change_is_a_new_space(self):
        a, b = profile(chart(concentration=4.0)), profile(chart(concentration=4.5))
        self.assertNotEqual(a.space().model_version, b.space().model_version)
        self.assertEqual(a.space(), profile(chart(concentration=4.0)).space())
        self.assertEqual(a.space().dim, 13 * 4096)


class PhaseEvidence(unittest.TestCase):
    def test_field_relation_hours_and_none(self):
        objs = (obj("t1", fields={"phase_code": "1"}), obj("t2", fields={"phase_code": 2.0}),
                obj("d1", kind="task_role_demand", rels=(("budget_for", "t2"),)),
                obj("r1", kind="rate_role", fields={"ph1_raw": "3", "ph2_raw": "1", "ph3_raw": "0"}),
                obj("r2", kind="rate_role", fields={"ph1_raw": "", "ph2_raw": "0"}),
                obj("x1", kind="reference_value"), obj("t3"))
        got = {a.object_id: a for a in assign_phases(profile(), objs)[0]}
        self.assertEqual(got["t1"].weights, (("1", 1.0),))
        self.assertEqual(got["t2"].weights, (("2", 1.0),))
        self.assertEqual(got["d1"].weights, (("2", 1.0),))
        self.assertEqual(got["r1"].state, "mixed")
        self.assertEqual(dict(got["r1"].weights), {"1": 0.75, "2": 0.25})
        self.assertEqual(got["r2"].state, "unphased")  # blank and zero are not evidence
        self.assertEqual(got["x1"].basis, "no phase rule for kind")
        self.assertEqual(got["t3"].state, "unphased")  # no field, no inference from neighbours or order

    def test_relation_rules_follow_one_hop_only(self):
        objs = (obj("t1", fields={"phase_code": "1"}), obj("d1", kind="task_role_demand", rels=(("budget_for", "t1"),)),
                obj("d2", kind="task_role_demand", rels=(("budget_for", "d1"),)),
                obj("d3", kind="task_role_demand", rels=(("budget_for", "missing"),)))
        got = {a.object_id: a for a in assign_phases(profile(), objs)[0]}
        self.assertEqual(got["d1"].dominant, "1")
        self.assertEqual(got["d2"].state, "unphased")
        self.assertEqual(got["d3"].state, "unphased")

    def test_unanchored_code_is_reported_not_guessed(self):
        a, diags = assign_phases(profile(), (obj("t9", fields={"phase_code": "9"}),))
        self.assertEqual(a[0].state, "unphased")
        self.assertTrue(any(d.startswith("unanchored_phase_code: t9") for d in diags))

    def test_assignment_contract(self):
        with self.assertRaises(ValueError):
            PhaseAssignment(object_id="a", state="phased", weights=(("1", 0.5), ("2", 0.5)), basis="x")
        with self.assertRaises(ValueError):
            PhaseAssignment(object_id="a", state="unphased", weights=(("1", 1.0),), basis="x")


class SparseSpace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.objs = run(workbook())[2].objects
        cls.res = splice(cls.objs)

    def test_containers_bindings_and_defects_stay_out(self):
        kinds = {r.kind for r in self.res.records}
        self.assertFalse(kinds & {"ingest_diagnostic", "project_document", "workbook_revision", "project_reference"})
        self.assertEqual(len(self.res.records) + len(self.res.excluded), len(self.objs))

    def test_layout_is_zero_based_increasing_unit_norm_and_round_trips_to_sparsevec(self):
        dim = self.res.space.dim
        for r in self.res.records:
            e = r.embedding
            self.assertTrue(all(b > a for a, b in zip(e.sparse_indices, e.sparse_indices[1:])))
            self.assertLess(max(e.sparse_indices), dim)
            self.assertAlmostEqual(float(np.linalg.norm(e.sparse_values)), 1.0, places=5)
            self.assertLess(min(e.sparse_indices), 4096)  # block 0 always present
            idx, val, d = parse_sparse(sparse_literal(e.sparse_indices, e.sparse_values, dim))
            self.assertEqual((idx, d), (e.sparse_indices, dim))
            if r.assignment.state == "unphased":
                self.assertEqual(r.bins_used, ())

    def test_cosine_factorises_into_content_times_coupling(self):
        prof = profile()
        recs = self.res.records
        by_id = {o.object_id: o for o in self.objs}
        dim = self.res.space.dim
        V = np.stack([dense(r, dim) for r in recs])
        C = np.stack([content_vector(tokens(prof, by_id[r.object_id]), prof.text_dim) for r in recs])
        from app.infrastructure.splice.kernels import bin_mass
        rows = [(r.assignment, 1.0 if r.assignment.state == "unphased" else prof.chart.shared_weight, bin_mass(prof.chart, r.assignment))
                for r in recs]
        K = NumpySpliceKernel.coupling_matrix(rows)
        np.testing.assert_allclose(V @ V.T, (C @ C.T) * K, atol=2e-6)

    def test_phased_against_unphased_coupling_is_root_s(self):
        p = profile(chart(shared_weight=0.36))
        r = splice((obj("a", title="rack build", fields={"phase_code": "1"}), obj("b", kind="note", title="rack build")), p)
        a, b = r.records
        dim = r.space.dim
        cos = float(dense(a, dim) @ dense(b, dim))
        ca, cb = (content_vector(tokens(p, o), p.text_dim) for o in (obj("a", title="rack build", fields={"phase_code": "1"}),
                                                                      obj("b", kind="note", title="rack build")))
        self.assertAlmostEqual(cos, float(ca @ cb) * 0.6, places=5)

    def test_words_hash_matches_the_ingest_tensorizer(self):
        p = profile(slot_fields=(), relation_slots=False)
        for o in self.objs[:20]:
            mine = content_vector(tokens(p, o), p.text_dim)
            theirs = hash_features([o], p.text_dim)[0]
            np.testing.assert_allclose(mine, theirs, atol=1e-12)

    def test_deterministic(self):
        again = splice(self.objs)
        self.assertEqual(self.res.model_dump_json(), again.model_dump_json())

    def test_store_and_read_back_by_space(self):
        store = build_memory()
        self.assertEqual(store_splice(store, self.res), len(self.res.records))
        r = self.res.records[0]
        with store() as u:
            self.assertEqual(u.embeddings.get(r.object_id, self.res.space), r.embedding)
            other = profile(chart(concentration=9.0)).space()
            self.assertIsNone(u.embeddings.get(r.object_id, other))


class Junctions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.objs = run(workbook())[2].objects
        cls.res = splice(cls.objs, junction_kinds=("wbs_task", "phase_scope"))

    def test_repeated_task_across_phases_is_a_candidate_scaled_by_the_chart(self):
        c = profile().chart
        hits = [j for j in self.res.junctions if set(j.shared_terms) == {"site", "walk"}]
        self.assertEqual(len(hits), 1)
        j = hits[0]
        self.assertEqual({j.phase_a, j.phase_b}, {"1", "2"})
        self.assertAlmostEqual(j.content_similarity, 1.0, places=6)
        self.assertAlmostEqual(j.phase_coupling, c.coupling("1", "2"), places=6)
        self.assertAlmostEqual(j.angular_distance_deg, 120.0, places=6)
        self.assertEqual(j.status, "candidate")

    def test_kinds_filter_and_threshold(self):
        kinds = {r.object_id: r.kind for r in self.res.records}
        for j in self.res.junctions:
            self.assertIn(kinds[j.a], ("wbs_task", "phase_scope"))
            self.assertNotEqual(j.phase_a, j.phase_b)
            self.assertGreaterEqual(j.content_similarity, 0.35)
        sims = [j.spliced_similarity for j in self.res.junctions]
        self.assertEqual(sims, sorted(sims, reverse=True))

    def test_chart_changes_coupling_never_content_and_never_writes_relations(self):
        sharp = splice(self.objs, profile(chart(concentration=32.0, shared_weight=0.1)), junction_kinds=("wbs_task", "phase_scope"))
        a = {(j.a, j.b): j for j in self.res.junctions}
        b = {(j.a, j.b): j for j in sharp.junctions}
        self.assertEqual(set(a), set(b))
        for k in a:
            self.assertAlmostEqual(a[k].content_similarity, b[k].content_similarity, places=9)
            self.assertLessEqual(b[k].phase_coupling, a[k].phase_coupling + 1e-9)
        self.assertEqual(run(workbook())[2].objects, self.objs)

    def test_slots_alone_never_make_a_junction(self):
        r = splice((obj("a", title="Procurement", fields={"phase_code": "1"}), obj("b", title="Commissioning", fields={"phase_code": "2"})),
                   junction_min_content=0.0)
        self.assertEqual(r.junctions, ())
        self.assertEqual(len(splice((obj("a", title="Procurement", fields={"phase_code": "1"}),
                                     obj("b", title="Commissioning", fields={"phase_code": "2"})),
                                    junction_min_content=0.0, junction_min_shared_terms=0).junctions), 1)

    def test_provenance_relations_are_not_slots(self):
        toks = tokens(profile(), obj("a", rels=(("in_revision", "r"), ("child_of", "p"), ("extracted_from", "d"))))
        self.assertIn("r:child_of", toks)
        self.assertNotIn("r:in_revision", toks)
        self.assertNotIn("r:extracted_from", toks)

    def test_cap(self):
        r = splice(self.objs, max_junctions=1)
        self.assertEqual(len(r.junctions), 1)
        self.assertGreaterEqual(r.junctions_considered, 1)


@unittest.skipUnless(os.environ.get("DATAMESH_PRIVATE_SPLICE_OBJECTS") and os.environ.get("DATAMESH_PRIVATE_SPLICE_PROFILE"),
                     "private splice check: set DATAMESH_PRIVATE_SPLICE_OBJECTS and DATAMESH_PRIVATE_SPLICE_PROFILE")
class PrivateSplice(unittest.TestCase):
    def test_private_objects_splice(self):
        objs = tuple(DomainObject.model_validate_json(line) for line in Path(os.environ["DATAMESH_PRIVATE_SPLICE_OBJECTS"]).read_text().splitlines() if line.strip())
        spec = json.loads(Path(os.environ["DATAMESH_PRIVATE_SPLICE_PROFILE"]).read_text())
        res = splice(objs, SpliceProfile.model_validate(spec["profile"]), **spec.get("request", {}))
        self.assertEqual(len(res.records) + len(res.excluded), len(objs))
        self.assertGreater(res.counts()["phased"], 0)
        for j in res.junctions:
            self.assertEqual(j.status, "candidate")
            self.assertTrue(math.isfinite(j.spliced_similarity))


if __name__ == "__main__":
    unittest.main()
