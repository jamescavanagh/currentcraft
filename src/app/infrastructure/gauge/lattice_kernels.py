"""Lattice-gauge reduction of reduced embeddings. numpy only (no scipy), deterministic in node ids.

Per node i: a local tangent frame ``O_i`` (K x 2, top two right-singular vectors of the centred
kNN patch) and a director angle ``phi_i`` in that frame. Per link (i, j): the connection angle
``A_ij`` of the polar rotation of ``O_i^T O_j`` (frame j -> frame i). Gauge transformation:
``O_i -> O_i R(alpha_i)`` gives ``phi_i -> phi_i - alpha_i`` and ``A_ij -> A_ij - alpha_i + alpha_j``.
Invariants: link ``L_ij = wrap(phi_j + A_ij - phi_i)``, triangle holonomy ``wrap(A_ij + A_jl + A_li)``,
defect charge ``(sum L - holonomy) / 2 pi`` and loop windings. Frame reflections are fixed by BFS
orientation plus the per-component ``net_holonomy_positive`` convention.

The ``alpha`` and ``flips`` hooks exist so the invariance adapter can apply gauge transformations
directly; production calls leave them ``None``.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

TWO_PI = 2.0 * np.pi
CAP = 1e6


def wrap(a):
    """Wrap angles to [-pi, pi)."""
    return (np.asarray(a) + np.pi) % TWO_PI - np.pi


def wrap_half(a):
    """Wrap axis angles to [-pi/2, pi/2)."""
    return (np.asarray(a) + np.pi / 2) % np.pi - np.pi / 2


def normalise(X: np.ndarray) -> np.ndarray:
    """Centre and scale to unit RMS: translation and scale drop out before any geometry."""
    Y = X - X.mean(axis=0)
    rms = float(np.sqrt((Y * Y).sum(axis=1).mean()))
    return Y / rms if rms > 0 else Y


def knn(X: np.ndarray, k: int, chunk: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """Exact k nearest neighbours (self excluded), ascending distance. Returns (indices, distances)."""
    n = len(X)
    sq = (X * X).sum(axis=1)
    idx = np.empty((n, k), dtype=np.int64)
    dist = np.empty((n, k))
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        d2 = np.maximum(sq[s:e, None] + sq[None, :] - 2.0 * (X[s:e] @ X.T), 0.0)
        d2[np.arange(e - s), np.arange(s, e)] = np.inf
        part = np.argpartition(d2, k - 1, axis=1)[:, :k]
        dd = np.take_along_axis(d2, part, axis=1)
        order = np.argsort(dd, axis=1, kind="stable")
        idx[s:e] = np.take_along_axis(part, order, axis=1)
        dist[s:e] = np.sqrt(np.take_along_axis(dd, order, axis=1))
    return idx, dist


def patches(X: np.ndarray, nb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Tangent frames O (N, K, 2) and top-3 patch eigenvalues lam (N, 3), descending."""
    n, K = X.shape
    O = np.empty((n, K, 2))
    lam = np.zeros((n, 3))
    for i in range(n):
        P = X[np.r_[i, nb[i]]]
        P = P - P.mean(axis=0)
        _, s, Vt = np.linalg.svd(P, full_matrices=False)
        w = s * s
        lam[i, : min(3, len(w))] = w[:3]
        O[i] = Vt[:2].T
    return O, lam


def _ratio(a, b):
    out = np.full(a.shape, CAP)
    ok = b > a * 1e-12
    out[ok] = np.minimum(a[ok] / b[ok], CAP)
    return out


def _polar(O, a, b):
    """Batched O_a^T O_b, its polar rotation angle, smallest singular value and determinant sign."""
    if len(a) == 0:
        z = np.zeros(0)
        return z, z, z
    M = np.einsum("ekp,ekq->epq", O[a], O[b])
    U, s, Vt = np.linalg.svd(M)
    R = U @ Vt
    return np.arctan2(R[:, 1, 0], R[:, 0, 0]), s.min(axis=1), np.sign(np.linalg.det(M))


def reduce_arrays(X: np.ndarray, rank: np.ndarray, flow: np.ndarray, *, k: int, planarity_min: float,
                  director_ratio_min: float, reliability_min: float, director_mode: str,
                  supersaturation_threshold: float, loops: tuple[tuple[int, ...], ...] = (),
                  alpha: Optional[np.ndarray] = None, flips: Optional[np.ndarray] = None) -> dict:
    """Full reduction. ``rank[i]`` is node i's position in id order (canonical edge and triangle sense).

    ``flow``: +1 supply, -1 demand, 0 neutral (supply_demand director only).
    """
    X = normalise(np.asarray(X, dtype=np.float64))
    n = len(X)
    axis = director_mode == "principal_axis"
    m = 2.0 if axis else 1.0
    wl = wrap_half if axis else wrap
    q = 0.5 if axis else 1.0

    nb, nd = knn(X, k)
    O, lam = patches(X, nb)
    planarity, anisotropy = _ratio(lam[:, 1], lam[:, 2]), _ratio(lam[:, 0], lam[:, 1])
    valid = planarity >= planarity_min

    if axis:
        dvec = O[:, :, 0].copy()
        valid &= anisotropy >= director_ratio_min
    else:
        dvec = np.zeros_like(X)
        for i in range(n):
            S = np.r_[i, nb[i]]
            f = flow[S]
            if (f > 0).any() and (f < 0).any():
                d = X[S][f > 0].mean(axis=0) - X[S][f < 0].mean(axis=0)
                p = O[i].T @ d
                if np.hypot(*p) > 1e-9 * max(np.linalg.norm(d), 1e-300):
                    dvec[i] = d
                    continue
            valid[i] = False

    if flips is not None:  # gauge hook: arbitrary reflection of individual frames
        O[flips, :, 1] *= -1.0

    # reliable links among valid nodes: union kNN, canonical (lower id, higher id)
    pairs = set()
    for i in range(n):
        if not valid[i]:
            continue
        for j in nb[i]:
            j = int(j)
            if valid[j]:
                pairs.add((i, j) if rank[i] < rank[j] else (j, i))
    E0 = sorted(pairs, key=lambda e: (rank[e[0]], rank[e[1]]))
    a0 = np.array([e[0] for e in E0], dtype=np.int64)
    b0 = np.array([e[1] for e in E0], dtype=np.int64)
    _, rel0, det0 = _polar(O, a0, b0)
    keep = rel0 >= reliability_min
    a1, b1, rel1, det1 = a0[keep], b0[keep], rel0[keep], det0[keep]

    # triangles of reliable links, ascending rank; z2 = product of orientation signs (gauge invariant)
    eid = {(int(a), int(b)): t for t, (a, b) in enumerate(zip(a1, b1))}
    nbrs: dict[int, set[int]] = {}
    for a, b in eid:
        nbrs.setdefault(a, set()).add(b)
        nbrs.setdefault(b, set()).add(a)
    tris = []
    for a, b in eid:
        for c in nbrs[a] & nbrs[b]:
            if rank[c] > rank[b]:
                tris.append((a, b, c))
    tris.sort(key=lambda t: (rank[t[0]], rank[t[1]], rank[t[2]]))
    tri = np.array(tris, dtype=np.int64).reshape(-1, 3)
    z2 = np.array([det1[eid[(a, b)]] * det1[eid[(b, c)]] * det1[eid[(a, c)]] for a, b, c in tris], dtype=np.int8)

    # orientation: BFS in id order, flip frames so links are rotations; conflicting links are dropped
    sgn = np.zeros(n)
    order = np.argsort(rank, kind="stable")
    for s0 in order:
        if sgn[s0] or s0 not in nbrs:
            continue
        sgn[s0] = 1.0
        dq = deque([int(s0)])
        while dq:
            i = dq.popleft()
            for j in sorted(nbrs[i], key=lambda v: rank[v]):
                e = (i, j) if rank[i] < rank[j] else (j, i)
                need = sgn[i] * det1[eid[e]]
                if not sgn[j]:
                    sgn[j] = need
                    dq.append(j)
    O[sgn < 0, :, 1] *= -1.0
    _, _, det2 = _polar(O, a1, b1)
    ok = det2 > 0
    conflicts = int((~ok).sum())
    a2, b2, rel2 = a1[ok], b1[ok], rel1[ok]

    # components of the kept connection graph
    comp = -np.ones(n, dtype=np.int64)
    adj: dict[int, list[int]] = {}
    for a, b in zip(a2, b2):
        adj.setdefault(int(a), []).append(int(b))
        adj.setdefault(int(b), []).append(int(a))
    c_id = 0
    for s0 in order:
        s0 = int(s0)
        if comp[s0] >= 0 or s0 not in adj:
            continue
        comp[s0] = c_id
        dq = deque([s0])
        while dq:
            i = dq.popleft()
            for j in adj[i]:
                if comp[j] < 0:
                    comp[j] = c_id
                    dq.append(j)
        c_id += 1

    kept = {(int(a), int(b)): t for t, (a, b) in enumerate(zip(a2, b2))}
    tri_ok = np.array([(a, b) in kept and (b, c) in kept and (a, c) in kept for a, b, c in tris], dtype=bool)

    def measure(O):
        A, _, _ = _polar(O, a2, b2)
        p = np.einsum("nkp,nk->np", O, dvec)
        phi = np.where(valid, np.arctan2(p[:, 1], p[:, 0]), 0.0)
        L = wl(phi[b2] + A - phi[a2])
        hol = np.full(len(tris), np.nan)
        ch = np.full(len(tris), np.nan)
        for t, (a, b, c) in enumerate(tris):
            if tri_ok[t]:
                e1, e2, e3 = kept[(a, b)], kept[(b, c)], kept[(a, c)]
                h = float(wrap(A[e1] + A[e2] - A[e3]))
                S = L[e1] + L[e2] - L[e3]
                hol[t] = h
                ch[t] = np.round((S - h) / TWO_PI / q) * q
        return A, phi, L, hol, ch

    A, phi, L, hol, ch = measure(O)
    # orientation convention: each component's net holonomy >= 0 (tie-break: net link)
    flip_any = False
    for c in range(c_id):
        in_c = np.array([comp[a] == c for a, _, _ in tris], dtype=bool) & tri_ok
        net = float(np.nansum(hol[in_c])) if in_c.any() else 0.0
        if abs(net) <= 1e-9:
            ec = comp[a2] == c
            net = float(L[ec].sum()) if ec.any() else 0.0
            if abs(net) <= 1e-9:
                continue
        if net < 0:
            O[comp == c, :, 1] *= -1.0
            flip_any = True
    if alpha is not None:  # gauge hook: rotate every frame by alpha_i
        c_, s_ = np.cos(alpha), np.sin(alpha)
        Rm = np.stack([np.stack([c_, -s_], -1), np.stack([s_, c_], -1)], -2)
        O = np.einsum("nkp,npq->nkq", O, Rm)
    if flip_any or alpha is not None:
        A, phi, L, hol, ch = measure(O)

    # operand gauges
    deg = np.zeros(n)
    coh_sum = np.zeros(n)
    cosl = np.cos(m * L)
    np.add.at(deg, a2, 1.0)
    np.add.at(deg, b2, 1.0)
    np.add.at(coh_sum, a2, cosl)
    np.add.at(coh_sum, b2, cosl)
    coh = np.where(deg > 0, coh_sum / np.maximum(deg, 1), 0.0)
    g_coh = float(cosl.mean()) if len(cosl) else None
    net_h = np.zeros(n)
    load = np.zeros(n)
    z2d = np.zeros(n)
    for t, (a, b, c) in enumerate(tris):
        for v in (a, b, c):
            if tri_ok[t]:
                net_h[v] += hol[t]
                load[v] += abs(ch[t])
            if z2[t] < 0:
                z2d[v] += 1
    spacing = nd.mean(axis=1)
    ldr = np.log(np.median(spacing) / np.maximum(spacing, 1e-300))
    gauges = np.stack([planarity, anisotropy, ldr, (np.exp(ldr) >= supersaturation_threshold).astype(float), coh,
                       np.where(deg > 0, coh - (g_coh or 0.0), 0.0), net_h, load, z2d, deg], axis=1)

    windings = []
    for cyc in loops:
        sL = sA = 0.0
        miss = 0
        for u, v in zip(cyc, cyc[1:] + cyc[:1]):
            e = (u, v) if rank[u] < rank[v] else (v, u)
            t = kept.get(e)
            if t is None:
                miss += 1
                continue
            sgn_e = 1.0 if e == (u, v) else -1.0
            sL += sgn_e * L[t]
            sA += sgn_e * A[t]
        if miss:
            windings.append(dict(complete=False, missing_links=miss))
        else:
            h = float(wrap(sA))
            w = (sL - h) / TWO_PI
            windings.append(dict(complete=True, missing_links=0, winding=float(w),
                                 quantized=float(np.round(w / q) * q), holonomy_deg=float(np.degrees(h))))

    return dict(node_gauges=gauges, node_mask=valid.copy(), director=wrap(phi), edge_index=np.stack([a2, b2]).astype(np.int64),
                edge_connection=wrap(A), edge_link=L, edge_reliability=rel2.astype(np.float64),
                triangles=tri.T.copy().astype(np.int64), triangle_holonomy=hol, triangle_charge=ch, triangle_z2=z2,
                n_valid=int(valid.sum()), orientation_conflicts=conflicts, global_link_coherence=g_coh,
                net_charge=float(np.nansum(ch)) if len(ch) else 0.0, loops=windings, charge_quantum=q)
