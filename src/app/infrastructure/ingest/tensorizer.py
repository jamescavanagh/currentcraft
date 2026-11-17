"""Tensorizer: domain objects to TensorRefs. Feature hashing (model-free), numeric with masks, typed edges, frozen PCA."""

from __future__ import annotations

import hashlib

import numpy as np

from app.application.ingest.contracts import (EDGE_INDEX_SPEC, EDGE_TYPE_SPEC, NUMERIC_MASK_SPEC, NUMERIC_SPEC,
                                              POSITIONS_SPEC, PROJ_COMPONENTS_SPEC, PROJ_MEAN_SPEC, TEXT_SPEC,
                                              FrozenProjection, TensorBatch)
from app.application.simulation.tensors import TensorContractError
from app.infrastructure.probe.kernels import words

TOKENIZER = "words-v1+blake2b-signed-hash-v1"


def hash_features(objects, dim):
    out = np.zeros((len(objects), dim), dtype=np.float64)
    for r, o in enumerate(objects):
        for tok in words(o.title or "", o.text):
            h = hashlib.blake2b(tok.encode(), digest_size=8).digest()
            out[r, int.from_bytes(h[:4], "little") % dim] += 1.0 if h[4] & 1 else -1.0
    out = np.sign(out) * np.log1p(np.abs(out))
    n = np.linalg.norm(out, axis=1, keepdims=True)
    return np.divide(out, n, out=np.zeros_like(out), where=n > 0)


class NumpyTensorizer:
    def __init__(self, store):
        self.store = store

    def fit_projection(self, name, text_dim, objects):
        if len(objects) < 3:
            raise ValueError("fit set needs at least 3 objects")
        F = hash_features(objects, text_dim)
        mean = F.mean(axis=0)
        U, s, Vt = np.linalg.svd(F - mean, full_matrices=False)
        if np.sum(s > 1e-12) < 3:
            raise ValueError("fit set has rank below 3; cannot fit a 3D projection")
        comps = Vt[:3].copy()
        for k in range(3):  # deterministic sign; handedness carries no meaning
            if comps[k, np.argmax(np.abs(comps[k]))] < 0:
                comps[k] *= -1
        total = float(np.sum(s ** 2))
        kept = float(np.sum(s[:3] ** 2)) / total
        ids = tuple(o.object_id for o in objects)
        dig = hashlib.sha256(comps.tobytes() + mean.tobytes() + "|".join(ids).encode() + f"{text_dim}|{TOKENIZER}".encode()).hexdigest()
        prod = "NumpyTensorizer.fit_projection"
        return FrozenProjection(name=name, text_dim=text_dim, tokenizer=TOKENIZER, fit_ids=ids, explained_share=kept,
                                discarded_share=1 - kept, digest=dig,
                                components=self.store.put(PROJ_COMPONENTS_SPEC, comps, producer=prod),
                                mean=self.store.put(PROJ_MEAN_SPEC, mean, producer=prod))

    def build(self, consumer, plan, entries):
        objs = [e.object for e in entries]
        prod = "NumpyTensorizer.build"
        F = hash_features(objs, plan.text_dim)
        refs = {"text": self.store.put(TEXT_SPEC, F.astype(np.float32), producer=prod)}
        if plan.numeric_fields:
            vals = np.zeros((len(objs), len(plan.numeric_fields)))
            mask = np.zeros_like(vals, dtype=bool)
            for r, o in enumerate(objs):
                for c, f in enumerate(plan.numeric_fields):
                    v = o.fields.get(f)
                    if isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v):
                        vals[r, c], mask[r, c] = float(v), True
            refs["numeric"] = self.store.put(NUMERIC_SPEC, vals, producer=prod)
            refs["numeric_mask"] = self.store.put(NUMERIC_MASK_SPEC, mask, producer=prod)
        row = {o.object_id: r for r, o in enumerate(objs)}
        types = {t: k for k, t in enumerate(plan.relation_types)}
        edges = [(r, row[rel.target_id], types[rel.type]) for r, o in enumerate(objs) for rel in o.relations
                 if rel.type in types and rel.target_id in row]
        if edges:
            E = np.array(edges, dtype=np.int64)
            refs["edge_index"] = self.store.put(EDGE_INDEX_SPEC, np.ascontiguousarray(E[:, :2].T), producer=prod)
            refs["edge_type"] = self.store.put(EDGE_TYPE_SPEC, np.ascontiguousarray(E[:, 2]), producer=prod)
        pdig = None
        if plan.projection is not None:
            p = plan.projection
            if p.text_dim != plan.text_dim or p.tokenizer != TOKENIZER:
                raise TensorContractError("projection was fit for another feature width or tokenizer")
            comps, mean = self.store.get(p.components), self.store.get(p.mean)
            refs["positions"] = self.store.put(POSITIONS_SPEC, (F - mean) @ comps.T, producer=prod)
            pdig = p.digest
        return TensorBatch(consumer=consumer, plan_digest=plan.digest(), projection_digest=pdig,
                           offsets=tuple(e.offset for e in entries), object_ids=tuple(o.object_id for o in objs),
                           content_sha256=tuple(o.provenance.content_sha256 for o in objs),
                           numeric_fields=plan.numeric_fields, relation_types=plan.relation_types, **refs)
