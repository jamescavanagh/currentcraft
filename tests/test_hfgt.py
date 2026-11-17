"""HFGT capability graph (0.9.9): golden fixtures from scripts/hfgt_reference.py and the paper's identities."""
import doctest
import json
import random
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.application.hfgt import (CapabilityConstraint, CapabilityRef, CandidateEdge, HfgtGraphRequest,  # noqa: E402
                                  buffer_graph, layers, operand_network, translate)
from app.application.process.contracts import ObjectIncidence  # noqa: E402
from app.infrastructure.hfgt import build_hfgt  # noqa: E402
from app.infrastructure.hfgt import kernels as K  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "hfgt"
START = ("equipment_kit:received@warehouse",)


def load(name):
    return json.loads((FIX / f"{name}.synthetic.json").read_text()), json.loads((FIX / f"{name}.expected.json").read_text())


def request(fx, constraints=(), mode="mask", **kw):
    return HfgtGraphRequest(frame_id="wme-rack-synthetic", executions=fx["executions"], buffers=fx["buffers"],
                            constraints=constraints, constraint_mode=mode, terminal_operands=fx["terminal_operands"],
                            start_operands=START, **kw)


def names(ids):
    return sorted(i.replace("|", " by ") for i in ids)


class Golden(unittest.TestCase):
    def test_matches_reference_oracle(self):
        adapter, store = build_hfgt()
        for name in ("wme_rack", "wme_rack_gaps"):
            fx, exp = load(name)
            for sc in fx["scenarios"]:
                for mode in ("drop", "mask"):
                    with self.subTest(fixture=name, scenario=sc["name"], mode=mode):
                        s = adapter.build(request(fx, sc["constraints"], mode))
                        e = next(x for x in exp["scenarios"] if x["scenario"] == sc["name"] and x["mode"] == mode)
                        ei = store.get(s.edge_index)
                        edges = sorted(f"{s.node_ids[a].replace('|', ' by ')} -> {s.node_ids[b].replace('|', ' by ')}" for a, b in ei.T)
                        self.assertEqual((s.dof_s, s.dof_rho, s.readiness), (e["dof_s"], e["dof_rho"], e["terminal_reachable"]))
                        self.assertEqual(names(s.dead_ends), sorted(e["dead_ends"]))
                        self.assertEqual(edges, e["edges"])
                        self.assertEqual(len(s.report.gaps), len(exp["gaps"]))

    def test_table_in_the_design_page(self):
        adapter, _ = build_hfgt()
        fx, _ = load("wme_rack")
        got = [(adapter.build(request(fx, sc["constraints"])).dof_s, adapter.build(request(fx, sc["constraints"])).dof_rho)
               for sc in fx["scenarios"]]
        self.assertEqual(got, [(10, 12), (9, 8), (9, 8)])


class Identities(unittest.TestCase):
    def setUp(self):
        self.fx, _ = load("wme_rack")
        self.adapter, self.store = build_hfgt()

    def test_system_concept_is_existence_minus_constraints(self):
        for sc in self.fx["scenarios"]:
            req = request(self.fx, sc["constraints"])
            caps = translate(req).capabilities
            s = self.adapter.build(req)
            self.assertEqual(s.dof_s, len(caps) - len(sc["constraints"]))
            x = self.store.get(s.x)
            self.assertEqual(int(x[:, 4].sum()), s.dof_s)  # 'available' column

    def test_or_over_resources_gives_buffer_graph_and_operand_network(self):
        tr = translate(request(self.fx))
        self.assertEqual(buffer_graph(tr), {("warehouse", "bench"), ("bench", "room201"), ("warehouse", "room201")})
        self.assertEqual(operand_network(tr), {("equipment_kit:received", "warehouse", "bench"),
                                               ("rack:built", "bench", "room201"),
                                               ("equipment_kit:received", "warehouse", "room201")})

    def test_incidence_product_equals_five_rules_on_random_systems(self):
        rng = random.Random(9)
        for trial in range(40):
            execs = []
            B = ["b0", "b1", "b2"][: rng.randint(1, 3)]
            for i in range(rng.randint(2, 9)):
                kind = rng.choice(["transform", "hold", "transport"])
                st = rng.choice(["s0", "s1", "s2"])
                if kind == "transform":
                    inc = [{"object_id": f"o{i}a", "object_kind": "k", "effect": "revises", "state_before": st,
                            "state_after": rng.choice(["s0", "s1", "s2"])}]
                    execs.append({"execution_id": f"t:{i}", "process": {"code": f"p{i % 3}", "name": "p", "function_classes": ["transform"]},
                                  "stage": "S", "at_buffer": rng.choice(B), "incidence": inc,
                                  "executed_by": [{"resource_id": f"r{rng.randint(0, 2)}", "resource_role": "x"}]})
                elif kind == "hold":
                    inc = [{"object_id": f"o{i}h", "object_kind": "k", "effect": "holds", "state_before": st, "state_after": st}]
                    execs.append({"execution_id": f"h:{i}", "process": {"code": "hold", "name": "h", "function_classes": ["hold"]},
                                  "stage": "S", "at_buffer": rng.choice(B), "incidence": inc,
                                  "executed_by": [{"resource_id": f"r{rng.randint(0, 2)}", "resource_role": "x"}]})
                else:
                    inc = [{"object_id": f"o{i}m", "object_kind": "k", "effect": "transfers", "state_before": st, "state_after": st,
                            "origin_buffer": rng.choice(B), "destination_buffer": rng.choice(B)}]
                    execs.append({"execution_id": f"m:{i}", "process": {"code": "move", "name": "m", "function_classes": ["transport"]},
                                  "stage": "S", "incidence": inc,
                                  "executed_by": [{"resource_id": "truck", "resource_role": "x"}]})
            req = HfgtGraphRequest(frame_id=f"rand-{trial}", executions=execs)
            s = self.adapter.build(req)  # the adapter raises if A_rho differs from the five-rule construction
            caps = translate(req).capabilities
            _, _, _, Mm, Mp = K.incidence(caps)
            W, A, _ = K.sequences(Mm, Mp, np.ones(len(caps), np.int64))
            self.assertTrue(np.array_equal(A, K.five_rule(caps)))
            self.assertTrue((W <= 1).all())  # Boolean and real products agree
            self.assertEqual(s.dof_rho, int(A.sum()))

    def test_layers_partition_capabilities(self):
        tr = translate(request(self.fx))
        lay = layers(tr, "input_operand_set")
        self.assertEqual(len(lay), len(tr.capabilities))  # exactly one layer per capability
        s = self.adapter.build(request(self.fx))
        et = self.store.get(s.edge_type)
        self.assertTrue(set(et.tolist()) <= set(range(len(s.layer_ids))))
        self.assertEqual(len(set(s.layer_ids)), len(s.layer_ids))

    def test_mask_and_drop_agree(self):
        for sc in self.fx["scenarios"]:
            a = self.adapter.build(request(self.fx, sc["constraints"], "mask"))
            b = self.adapter.build(request(self.fx, sc["constraints"], "drop"))
            self.assertEqual((a.dof_s, a.dof_rho, a.readiness, sorted(a.dead_ends)), (b.dof_s, b.dof_rho, b.readiness, sorted(b.dead_ends)))
            self.assertGreaterEqual(len(a.node_ids), len(b.node_ids))


class Rules(unittest.TestCase):
    def setUp(self):
        self.fx, _ = load("wme_rack")
        self.adapter, self.store = build_hfgt()

    def test_simulated_work_never_creates_a_capability(self):
        ex = [dict(e) for e in self.fx["executions"]]
        ex[2]["epistemic_status"] = "simulated"
        tr = translate(request({**self.fx, "executions": ex}))
        self.assertNotIn("refined:hold(equipment_kit:received):bench->bench|builder", {c.node_id for c in tr.capabilities})
        self.assertTrue(any("simulated" in g.reason for g in tr.report.gaps))

    def test_constraint_on_a_missing_capability_is_an_error(self):
        bad = [{"capability": {"process": "transform:weld@bench", "resource_id": "builder"}, "reason": "typo"}]
        with self.assertRaises(ValueError):
            self.adapter.build(request(self.fx, bad))

    def test_people_are_never_operands(self):
        ex = [dict(e) for e in self.fx["executions"]]
        ex[0] = {**ex[0], "incidence": [{"object_id": "clerk", "object_kind": "person", "effect": "holds",
                                         "state_before": "x", "state_after": "x"}]}
        with self.assertRaises(ValidationError):
            request({**self.fx, "executions": ex})

    def test_undeclared_buffer_is_a_gap(self):
        tr = translate(request({**self.fx, "buffers": [b for b in self.fx["buffers"] if b["buffer_id"] != "room201"]}))
        self.assertTrue(any("not declared" in g.reason for g in tr.report.gaps))

    def test_constraint_time_window(self):
        k = CapabilityConstraint(capability=CapabilityRef(process="refined:hold(rack:built):bench->room201", resource_id="truck"),
                                 reason="oversize", valid_from=datetime(2026, 12, 1, tzinfo=timezone.utc))
        before = self.adapter.build(request(self.fx, [k], as_of=datetime(2026, 11, 16, tzinfo=timezone.utc)))
        during = self.adapter.build(request(self.fx, [k], as_of=datetime(2026, 12, 2, tzinfo=timezone.utc)))
        self.assertEqual((before.readiness, during.readiness), ("reachable", "blocked: constraints"))

    def test_candidates_stay_apart(self):
        src = CapabilityRef(process="transform:build_rack@bench", resource_id="builder")
        dst = CapabilityRef(process="control:commission_rack@room201", resource_id="commissioner")
        s = self.adapter.build(request(self.fx, candidates=[CandidateEdge(source=src, target=dst, score=0.61, origin="splice:junction")]))
        self.assertEqual(s.dof_rho, 12)
        self.assertEqual(self.store.get(s.candidate_edge_index).shape, (2, 1))

    def test_tensors_follow_pyg_conventions(self):
        s = self.adapter.build(request(self.fx))
        x, ei, ea, et = (self.store.get(r) for r in (s.x, s.edge_index, s.edge_attr, s.edge_type))
        self.assertEqual((x.shape, ei.shape, ea.shape, et.shape), ((10, 12), (2, 12), (12, 5), (12,)))
        self.assertEqual((str(x.dtype), str(ei.dtype)), ("float32", "int64"))
        self.assertEqual(int(ea[:, 0].sum()), len(s.witnesses))

    def test_single_capability_has_no_edges(self):
        one = [self.fx["executions"][0]]
        s = self.adapter.build(HfgtGraphRequest(frame_id="one", executions=one, buffers=self.fx["buffers"]))
        self.assertEqual((s.dof_s, s.dof_rho), (1, 0))
        self.assertEqual(self.store.get(s.edge_index).shape, (2, 0))


class Doctests(unittest.TestCase):
    def test_translation_doctests(self):
        from app.application.hfgt import translation
        self.assertEqual(doctest.testmod(translation).failed, 0)


class ProcessBuffers(unittest.TestCase):
    def test_transfer_buffers_go_together_and_only_on_transfers(self):
        with self.assertRaises(ValidationError):
            ObjectIncidence(object_id="o", effect="transfers", state_before="a", state_after="a", origin_buffer="x")
        with self.assertRaises(ValidationError):
            ObjectIncidence(object_id="o", effect="holds", state_before="a", state_after="a", origin_buffer="x", destination_buffer="y")
        ObjectIncidence(object_id="o", effect="transfers", state_after="a", origin_buffer="x", destination_buffer="y")
        ObjectIncidence(object_id="o", effect="transfers", state_after="a")  # 0.9.8 payloads still validate


if __name__ == "__main__":
    unittest.main()
