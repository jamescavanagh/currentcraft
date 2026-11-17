"""Implements HfgtGraphPort with numpy and the in-memory tensor store."""
from __future__ import annotations

import numpy as np

from app.application.hfgt.contracts import (EDGE_FEATURES, NODE_FEATURES, CapabilityGraphSample, HfgtGraphRequest,
                                            HfgtTranslation)
from app.application.hfgt.translation import check_constraints, layers, translate
from app.application.simulation.tensors import TensorContractError
from app.infrastructure.tensors.numpy_store import InMemoryNumpyTensorStore

from . import kernels as K

FC = {"transform": 0, "transport": 1, "hold": 2, "control": 3}


class NumpyHfgtGraphAdapter:
    """Records -> capabilities -> M-/M+ -> A_rho -> PyG-style tensors, plus readiness and dead ends."""

    name = "numpy.HfgtGraph/v1"

    def __init__(self, store: InMemoryNumpyTensorStore):
        self.store = store

    def build(self, req: HfgtGraphRequest) -> CapabilityGraphSample:
        tr: HfgtTranslation = translate(req)
        blocked = check_constraints(req, tr)
        caps = tuple(c for c in tr.capabilities if req.constraint_mode == "mask" or c.node_id not in blocked)
        n = len(caps)
        avail = np.array([0 if c.node_id in blocked else 1 for c in caps], np.int64)
        if n:
            _L, _B, places, Mm, Mp = K.incidence(caps)
            W, A, self_seq = K.sequences(Mm, Mp, avail)
            oracle = K.five_rule(caps) * avail[:, None] * avail[None, :]
            if not np.array_equal(oracle, A):
                raise TensorContractError("A_rho differs from the five-rule construction")
            if not (np.minimum(W, 1) == (W > 0)).all() or W.max(initial=0) > 1:
                raise TensorContractError("a capability pulls or injects at more than one place per operand pair")
        else:
            places, Mm, Mp = [], np.zeros((0, 0), np.int64), np.zeros((0, 0), np.int64)
            A, self_seq = np.zeros((0, 0), np.int64), np.zeros(0, np.int64)
        terminal_ops = set(req.terminal_operands)
        terminal = np.array([any(op in terminal_ops for op, _ in c.injects) for c in caps], bool)
        src, dst = np.nonzero(A)
        lay = layers(HfgtTranslation(capabilities=caps, report=tr.report), req.layer_scheme)
        layer_ids = tuple(dict.fromkeys(lay))
        edge_type = np.array([layer_ids.index(lay[b]) for b in dst], np.int64)
        witnesses = []
        for e, (a, b) in enumerate(zip(src, dst)):
            for r in np.nonzero(Mp[:, a] * Mm[:, b])[0]:
                witnesses.append((e, places[r][0], places[r][1]))
        stage = [set(c.stages) for c in caps]
        buf_in = [{y for _, y in c.pulls} for c in caps]
        buf_out = [{y for _, y in c.injects} for c in caps]
        n_w = [sum(1 for w in witnesses if w[0] == e) for e in range(len(src))]
        attr = np.array([[float(n_w[e]), float(buf_in[a] != buf_out[b]), float(caps[a].resource_id == caps[b].resource_id),
                          float(not (stage[a] & stage[b])), float(caps[a].nonconsuming or caps[b].nonconsuming)]
                         for e, (a, b) in enumerate(zip(src, dst))], np.float64)
        attr = attr.reshape(-1, len(EDGE_FEATURES))
        x = np.array([[float(c.capability_class == "transform"), float(c.capability_class == "transport"),
                       float(c.capability_class == "hold"), float(c.capability_class == "control"), float(avail[i]),
                       float(c.evidenced), float(np.log1p(c.evidence_count)), float(len({op for op, _ in c.pulls})),
                       float(len({op for op, _ in c.injects})), float(c.nonconsuming), float(self_seq[i]), float(terminal[i])]
                      for i, c in enumerate(caps)], np.float64).reshape(-1, len(NODE_FEATURES))
        # readiness: reachable / blocked / unknown / unreachable (a structural reading, never a release)
        if req.start_operands:
            starts = set(req.start_operands)
            sources = [i for i, c in enumerate(caps) if avail[i] and any(f"{op}@{y}" in starts for op, y in c.pulls)]
        else:
            sources = [i for i in range(n) if avail[i] and not A[:, i].any()]
        targets = [i for i in range(n) if terminal[i]]
        reach = bool(sources and targets and K.reachable(A, sources, targets))
        if reach:
            readiness = "reachable"
        elif tr.report.gaps:
            readiness = "unknown: translation gaps"
        elif blocked:
            readiness = "blocked: constraints"
        else:
            readiness = "unreachable"
        dead = tuple(caps[i].node_id for i in range(n) if avail[i] and not A[i].any() and not terminal[i])
        idx = {c.node_id: i for i, c in enumerate(caps)}
        cand = [(idx[k.source.node_id], idx[k.target.node_id]) for k in req.candidates
                if k.source.node_id in idx and k.target.node_id in idx]
        specs = CapabilityGraphSample.TENSORS
        put = lambda name, arr: self.store.put(specs[name], arr, self.name)  # noqa: E731
        return CapabilityGraphSample(
            frame_id=req.frame_id, request_digest=req.digest(), node_ids=tuple(c.node_id for c in caps), layer_ids=layer_ids,
            witnesses=tuple(witnesses), dof_s=int(avail.sum()), dof_rho=int(A.sum()), readiness=readiness, dead_ends=dead,
            report=tr.report, constraint_mode=req.constraint_mode,
            x=put("x", x.astype(np.float32)),
            edge_index=put("edge_index", np.stack([src, dst]).astype(np.int64).reshape(2, -1)),
            edge_attr=put("edge_attr", attr.astype(np.float32)),
            edge_type=put("edge_type", edge_type),
            candidate_edge_index=put("candidate_edge_index", np.array(cand, np.int64).reshape(-1, 2).T.copy()) if req.candidates else None,
        )
