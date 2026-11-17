"""Numpy adapter for the enrichment port."""

from __future__ import annotations

import numpy as np

from app.application.enrichment.contracts import (EMBEDDINGS_SPEC, FREE_SPEC, LABELS_SPEC, NUCLEATIONS_SPEC, SPARSE_SPEC,
                                                  ArmStats, EnrichmentRequest, EnrichmentResult, PassRecord,
                                                  ShortcutCandidate, SmallWorldStats)
from app.application.simulation.tensors import TensorContractError

from . import kernels as K


class NumpyEnrichmentAdapter:
    def __init__(self, store):
        self.store = store

    def enrich(self, request: EnrichmentRequest) -> EnrichmentResult:
        run = request.plate_run
        feats = list(run.feature_names)
        plate = self.store.get(run.plate)
        times = self.store.get(run.times)
        Z, Zd = plate[:, feats.index("zeta")], plate[:, feats.index("zeta_dot")]
        if len(times) < 3:
            raise TensorContractError("plate run needs at least 3 snapshots")
        get = lambda r: None if r is None else self.store.get(r)
        out = K.run_chamber(self.store.get(request.embeddings), request.slab.origin, request.slab.normal,
                            get(request.labels_real), get(request.labels_null), Z, Zd, times, request.params,
                            request.criteria, request.salt, request.path_sources, request.null_mode)
        ids = request.ids
        passes = tuple(PassRecord(anomalous=p["order"] in ("cond-off", "cond-noact", "cond-first"), **p)
                       for a in out["arms"] for p in a.passes)
        shortcuts = tuple(ShortcutCandidate(arm=arm, a=ids[i], b=ids[j], co_passes=co, hops=hop, cross_cluster=cross,
                                            phase_bin=b, score=score)
                          for arm, lst in out["shortcuts"] for i, j, co, hop, cross, b, score in lst)
        stats = tuple(ArmStats(**{**s, "small_world": SmallWorldStats(**s["small_world"])}) for s in out["stats"])
        cnt = {s.arm: s.shortcut_count for s in stats}
        prod = "NumpyEnrichmentAdapter"
        return EnrichmentResult(enrichment_id=request.enrichment_id, request_digest=request.digest(),
                                embeddings_sha256=request.embeddings.sha256, plate_request_digest=run.request_digest,
                                ids=ids, h_scale=out["h_scale"], passes=passes, shortcuts=shortcuts, arm_stats=stats,
                                null_mode=request.null_mode, shortcut_excess_on=cnt["real-on"] - cnt["null-on"],
                                shortcut_excess_off=cnt["real-off"] - cnt["null-off"],
                                sparse_code=self.store.put(SPARSE_SPEC, out["sparse"], producer=prod),
                                nucleations=self.store.put(NUCLEATIONS_SPEC, out["nucleations"], producer=prod),
                                ion_free_counts=self.store.put(FREE_SPEC, out["free"], producer=prod))


def put_embedding_matrix(store, X):
    """Explicit infrastructure conversion of frozen projected rows into the shared store."""
    return store.put(EMBEDDINGS_SPEC, np.array(X, dtype=np.float64, copy=True), producer="enrichment-input")


def put_labels(store, labels):
    return store.put(LABELS_SPEC, np.array(labels, dtype=np.int64, copy=True), producer="enrichment-input")
