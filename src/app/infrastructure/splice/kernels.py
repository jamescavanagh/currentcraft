"""Numpy splice kernel: signed hashed content, von Mises phase blocks, exact coupling matrix for junctions."""

from __future__ import annotations

import hashlib
import math
from collections import Counter

import numpy as np

from app.application.persistence.contracts import EmbeddingRecord
from app.application.splice.contracts import TOKENIZER, SpliceJunction, SpliceRecord, SpliceResult
from app.infrastructure.probe.kernels import words

MAX_JUNCTION_ROWS = 20000


def _slot(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip().lower()


def tokens(profile, o):
    """(token, weight) multiset: words of title + text at weight 1, slot tokens at slot_weight."""
    t = Counter(words(o.title or "", o.text))
    out = {w: float(n) for w, n in t.items()}
    for f in profile.slot_fields:
        v = o.kind if f == "kind" else o.fields.get(f)
        if v is not None and v != "" and not isinstance(v, bool):
            out[f"f:{f}={_slot(v)}"] = out.get(f"f:{f}={_slot(v)}", 0.0) + profile.slot_weight
    if profile.relation_slots:
        for rel in o.relations:
            if rel.type in profile.relation_slot_exclude:
                continue
            k = f"r:{rel.type}"
            out[k] = out.get(k, 0.0) + profile.slot_weight
    return out


def content_vector(toks, dim):
    """Same hash as the ingest tensorizer: blake2b, bucket from bytes 0-3, sign from byte 4; signed log1p; L2."""
    v = np.zeros(dim, dtype=np.float64)
    for tok, w in toks.items():
        h = hashlib.blake2b(tok.encode(), digest_size=8).digest()
        v[int.from_bytes(h[:4], "little") % dim] += w if h[4] & 1 else -w
    v = np.sign(v) * np.log1p(np.abs(v))
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def bin_mass(chart, assignment):
    """Mixture of the chart's bin distributions over the assignment shares; zeros when unphased."""
    w = np.zeros(chart.bins)
    for code, share in assignment.weights:
        w += share * np.asarray(chart.bin_weights(code))
    return w


def _angle_gap(a, b):
    d = abs(a - b) % (2 * math.pi)
    return math.degrees(min(d, 2 * math.pi - d))


class NumpySpliceKernel:
    name = "NumpySpliceKernel"
    version = "1"

    def encode(self, request, assignments):
        prof, chart = request.profile, request.profile.chart
        D, s = prof.text_dim, chart.shared_weight
        space = prof.space()
        keep = [o for o in request.objects if o.kind not in prof.excluded_kinds]
        if len(keep) != len(assignments) or any(o.object_id != a.object_id for o, a in zip(keep, assignments)):
            raise ValueError("assignments must align with the non-excluded objects in input order")
        excluded = [o.object_id for o in request.objects if o.kind in prof.excluded_kinds]
        diags, records, rows, vecs, words_of = [], [], [], [], []
        for o, a in zip(keep, assignments):
            toks = tokens(prof, o)
            c = content_vector(toks, D)
            if not np.any(c):
                excluded.append(o.object_id)
                diags.append(f"no_tokens: {o.object_id} hashed to an empty vector; kept out of the space")
                continue
            w = bin_mass(chart, a)
            shared = 1.0 if a.state == "unphased" else s
            blocks = [(0, math.sqrt(shared))] + [(1 + b, math.sqrt((1.0 - shared) * w[b])) for b in range(chart.bins) if w[b] > 0]
            blocks = [(blk, amp) for blk, amp in blocks if amp > 0]
            nz = np.flatnonzero(c)
            idx = np.concatenate([blk * D + nz for blk, _ in blocks])
            val = np.concatenate([amp * c[nz] for _, amp in blocks]).astype(np.float32).astype(np.float64)
            emb = EmbeddingRecord(object_id=o.object_id, space=space, sparse_indices=tuple(int(i) for i in idx),
                                  sparse_values=tuple(float(x) for x in val), recorded_at=request.recorded_at)
            records.append(SpliceRecord(object_id=o.object_id, kind=o.kind, content_sha256=o.provenance.content_sha256,
                                        assignment=a, tokens=len(toks), bins_used=tuple(blk - 1 for blk, _ in blocks if blk > 0),
                                        embedding=emb))
            rows.append((a, shared, w))
            vecs.append(c)
            words_of.append(set(words(o.title or "", o.text)))
        junctions, considered = self._junctions(request, records, rows, vecs, words_of, diags)
        return SpliceResult(profile_digest=prof.digest(), chart_digest=chart.digest(), space=space, records=tuple(records),
                            excluded=tuple(excluded), junctions=junctions, junctions_considered=considered, diagnostics=tuple(diags))

    @staticmethod
    def coupling_matrix(rows):
        """K_ij = sqrt(s_i s_j) + sqrt((1-s_i)(1-s_j)) * sum_b sqrt(w_ib w_jb). Spliced cosine = content cosine * K."""
        S = np.sqrt(np.array([sh for _, sh, _ in rows]))
        R = np.sqrt(1.0 - S ** 2)
        Q = np.sqrt(np.stack([w for _, _, w in rows])) * R[:, None]
        return np.clip(np.outer(S, S) + Q @ Q.T, 0.0, 1.0)

    def _junctions(self, request, records, rows, vecs, words_of, diags):
        if request.max_junctions == 0 or len(records) < 2:
            return (), 0
        if len(records) > MAX_JUNCTION_ROWS:
            diags.append(f"junctions_skipped: {len(records)} records exceed {MAX_JUNCTION_ROWS}")
            return (), 0
        chart = request.profile.chart
        C = np.clip(np.stack(vecs) @ np.stack(vecs).T, -1.0, 1.0)
        K = self.coupling_matrix(rows)
        jk = set(request.junction_kinds)
        dom = [a.dominant if not jk or rec.kind in jk else None for (a, _, _), rec in zip(rows, records)]
        df = Counter(w for ws in words_of for w in ws)
        cand = []
        n = len(records)
        for i in range(n):
            if dom[i] is None:
                continue
            for j in range(i + 1, n):
                if dom[j] is None or dom[j] == dom[i] or C[i, j] < request.junction_min_content:
                    continue
                if len(words_of[i] & words_of[j]) < request.junction_min_shared_terms:
                    continue
                cand.append((float(C[i, j] * K[i, j]), float(C[i, j]), i, j))
        cand.sort(key=lambda t: (-t[0], -t[1], records[t[2]].object_id, records[t[3]].object_id))
        out = []
        for sp, cs, i, j in cand[:request.max_junctions]:
            a, b = (i, j) if records[i].object_id < records[j].object_id else (j, i)
            terms = sorted(words_of[a] & words_of[b], key=lambda w: (df[w], w))[:5]
            out.append(SpliceJunction(a=records[a].object_id, b=records[b].object_id, phase_a=dom[a], phase_b=dom[b],
                                      content_similarity=round(cs, 9), phase_coupling=round(float(K[i, j]), 9),
                                      spliced_similarity=round(sp, 9),
                                      angular_distance_deg=round(_angle_gap(chart.angle_rad(dom[a]), chart.angle_rad(dom[b])), 9),
                                      shared_terms=tuple(terms)))
        return tuple(out), len(cand)


__all__ = ["NumpySpliceKernel", "TOKENIZER", "tokens", "content_vector", "bin_mass"]
