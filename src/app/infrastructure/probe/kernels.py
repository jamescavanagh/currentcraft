"""Probe kernels (infrastructure only). Design source: docs/pipelines/PROBE.md."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

import numpy as np

from app.infrastructure.gauge.winding import measure_velocity_winding
from app.infrastructure.plate import kernels as PK

TWO_PI = 2.0 * math.pi
STOP = frozenset("the and for with from into that this are was were has have not but per via its our your their of to in on at by an or as is be it".split())


# ----------------------------------------------------------------------------- geometry

def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def basis(n):
    """Deterministic in-plane axes for a unit normal: least-aligned world axis, Gram-Schmidt."""
    n = unit(n)
    ax = np.eye(3)[int(np.argmin(np.abs(n)))]
    a1 = unit(ax - (ax @ n) * n)
    return a1, np.cross(n, a1)


def plate_frame(normal, tilt_deg, yaw_deg, phase):
    n = unit(normal)
    b1, b2 = basis(n)
    bt, ps = math.radians(tilt_deg), math.radians(yaw_deg)
    ne = unit(math.cos(bt) * n + math.sin(bt) * (math.cos(ps) * b1 + math.sin(ps) * b2))
    a1, a2 = basis(ne)
    c, s = math.cos(phase), math.sin(phase)
    return ne, c * a1 + s * a2, -s * a1 + c * a2


def slab(X, origin, ne, eu, ev, offset, w):
    r = X - np.asarray(origin, dtype=np.float64)
    h = r @ ne
    mask = np.abs(h - offset) <= w
    return mask, np.c_[r @ eu, r @ ev]


# ----------------------------------------------------------------------------- ring readings

def ring_readings(vel, jac, phi, radius, gradient_floor=1e-8, speed_floor=1e-8):
    """Circulation, eta_kin and leakage on a ring from sampled velocity (K,2) and Jacobian (K,2,2)."""
    er = np.c_[np.cos(phi), np.sin(phi)]
    et = np.c_[-np.sin(phi), np.cos(phi)]
    gaps = np.diff(np.r_[phi, phi[0] + TWO_PI])
    ds = radius * gaps
    length = float(ds.sum())
    ut, ur = np.sum(vel * et, axis=1), np.sum(vel * er, axis=1)
    circulation = float(np.sum(ut * ds))
    S = 0.5 * (jac + np.transpose(jac, (0, 2, 1)))
    W = 0.5 * (jac - np.transpose(jac, (0, 2, 1)))
    w2 = np.sum(W * W, axis=(1, 2)) @ ds
    s2 = np.sum(S * S, axis=(1, 2)) @ ds
    masks = []
    eta = None
    if (w2 + s2) <= gradient_floor * length:
        masks.append("eta_kin: gradient below floor")
    else:
        eta = float(w2 / (w2 + s2))
    flux_r, flux_t = float(np.abs(ur) @ ds), float(np.abs(ut) @ ds)
    leak = None
    if flux_r + flux_t <= speed_floor * length:
        masks.append("leakage: speed below floor")
    else:
        leak = flux_r / (flux_r + flux_t)
    return circulation, eta, leak, masks


def linear_field(L, pts):
    L = np.asarray(L, dtype=np.float64)
    return pts @ L.T, np.broadcast_to(L, (len(pts), 2, 2)).copy()


# ----------------------------------------------------------------------------- terms

def _split_camel(t):
    t = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", t)
    return re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", t)


def words(title, text=None):
    toks = re.findall(r"[a-z0-9]+", _split_camel(title + " " + (text or "")).lower())
    return [w for w in toks if len(w) >= 3 and w not in STOP]


def contrast(sub_counts, ref_counts, top, alpha=0.5):
    """Smoothed log-odds of each term in the subset against the reference."""
    V = max(1, len(ref_counts | sub_counts))
    ns, nr = sum(sub_counts.values()), sum(ref_counts.values())
    out = []
    for t, c in sub_counts.items():
        w = math.log((c + alpha) / (ns + alpha * V)) - math.log((ref_counts.get(t, 0) + alpha) / (nr + alpha * V))
        out.append((t, w, c))
    out.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return out[:top]


def tfidf(doc_counts, doc_freq, ndocs, top):
    out = [(t, c * math.log((1 + ndocs) / (1 + doc_freq.get(t, 0))) + c * 1e-9, c) for t, c in doc_counts.items()]
    out.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return out[:top]


# ----------------------------------------------------------------------------- clustering

def mutual_knn_components(P, k, min_size):
    n = len(P)
    if n < 2:
        return [], list(range(n))
    k = min(k, n - 1)
    d = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=2)
    np.fill_diagonal(d, np.inf)
    nb = np.argsort(d, axis=1, kind="stable")[:, :k]
    sets = [set(map(int, r)) for r in nb]
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for i in range(n):
        for j in sets[i]:
            if i in sets[j]:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    comps = sorted((sorted(g) for g in groups.values() if len(g) >= min_size), key=lambda g: (-len(g), g[0]))
    used = {i for g in comps for i in g}
    return comps, [i for i in range(n) if i not in used]


def cluster_id(members):
    return "cl-" + hashlib.sha256(",".join(sorted(members)).encode()).hexdigest()[:16]
