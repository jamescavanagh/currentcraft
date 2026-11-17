"""Chamber kernels (infrastructure only). Port of the Condensation Chamber v8 rules; docs/pipelines/EMBEDDING_ENRICHMENT.md."""

from __future__ import annotations

import math
from collections import deque

import numpy as np

TWO_PI = 2.0 * math.pi
BINS = 12
ARMS = (("real-on", "real", True), ("real-off", "real", False), ("null-on", "null", True), ("null-off", "null", False))


def knn(X, k, chunk=512):
    """Exact kNN (Euclidean), stable ties by index. Returns neighbour indices (N,k) and weights exp(-d/d0)."""
    n = len(X)
    nb = np.empty((n, k), dtype=np.int64)
    dist = np.empty((n, k))
    sq = np.sum(X * X, axis=1)
    for s in range(0, n, chunk):
        d2 = np.maximum(sq[s:s + chunk, None] + sq[None, :] - 2 * X[s:s + chunk] @ X.T, 0.0)
        d2[np.arange(len(d2)), np.arange(s, s + len(d2))] = np.inf
        idx = np.argsort(d2, axis=1, kind="stable")[:, :k]
        nb[s:s + chunk] = idx
        dist[s:s + chunk] = np.sqrt(np.take_along_axis(d2, idx, axis=1))
    d0 = float(np.median(dist)) or 1.0
    return nb, np.exp(-dist / d0)


def shuffle_axes(X, salt):
    """Permute each axis independently: same marginals, joint structure destroyed."""
    rng = np.random.default_rng(salt)
    Y = X.copy()
    for a in range(X.shape[1]):
        Y[:, a] = X[rng.permutation(len(X)), a]
    return Y


def height_preserving_shuffle(X, origin, normal, salt):
    """Keep each record's off-plane height h; give it another record's in-plane position."""
    n = np.asarray(normal, dtype=np.float64); n = n / np.linalg.norm(n)
    o = np.asarray(origin, dtype=np.float64)
    h = (X - o) @ n
    inplane = (X - o) - h[:, None] * n[None, :]
    perm = np.random.default_rng(salt).permutation(len(X))
    return o + inplane[perm] + h[:, None] * n[None, :]


def adjacency(nb):
    n = len(nb)
    adj = [set() for _ in range(n)]
    for i in range(n):
        for j in nb[i]:
            adj[i].add(int(j)); adj[int(j)].add(i)
    return adj


def bfs(adj, src):
    d = np.full(len(adj), -1, dtype=np.int64)
    d[src] = 0
    q = deque([src])
    while q:
        a = q.popleft()
        for b in adj[a]:
            if d[b] < 0:
                d[b] = d[a] + 1
                q.append(b)
    return d


def clustering(adj):
    vals = []
    for nbrs in adj:
        nbrs = list(nbrs)
        k = len(nbrs)
        if k < 2:
            vals.append(0.0)
            continue
        links = sum(1 for x in range(k) for y in range(x + 1, k) if nbrs[y] in adj[nbrs[x]])
        vals.append(2.0 * links / (k * (k - 1)))
    return float(np.mean(vals))


def path_stats(adj, sources):
    total, count, unreachable, inv = 0, 0, 0, 0.0
    for s in sources:
        d = bfs(adj, int(s))
        mask = np.arange(len(adj)) != s
        reach = d[mask]
        unreachable += int(np.sum(reach < 0))
        ok = reach[reach > 0]
        total += int(ok.sum()); count += len(ok); inv += float(np.sum(1.0 / ok))
    pairs = len(sources) * (len(adj) - 1)
    return (total / count if count else None), (unreachable / pairs if pairs else 0.0), (inv / pairs if pairs else 0.0)


def orbit_phase(Z, Zd, Zwall, Zref):
    a = math.atan2(-Zd / Zref, Z / Zwall)
    return a + TWO_PI if a < 0 else a


def splice_kind(pz, pzd, z, zd):
    if pz < 0 <= z:
        return "cross_up"
    if pz > 0 >= z:
        return "cross_down"
    if pzd > 0 >= zd:
        return "apex_top"
    if pzd < 0 <= zd:
        return "apex_bottom"
    return None


def order_of(t_cond, t_act, act):
    if t_cond is None:
        return "act-only" if t_act is not None else "quiet"
    if not act:
        return "cond-off"
    if t_act is None:
        return "cond-noact"
    return "cond-first" if t_cond < t_act else "act-first"


class _Geometry:
    def __init__(self, X, origin, normal, k):
        n = np.asarray(normal, dtype=np.float64)
        n = n / np.linalg.norm(n)
        self.h = (X - np.asarray(origin, dtype=np.float64)) @ n
        self.hq = float(np.quantile(np.abs(self.h), 0.95, method="lower")) or 1.0
        self.nb, self.wt = knn(X, k)
        self.wsum = self.wt.sum(axis=1)


class _Arm:
    def __init__(self, key, emb, act, n):
        self.key, self.emb, self.act = key, emb, act
        self.ion = np.zeros(n); self.drop = np.zeros(n)
        self.code = np.zeros((n, BINS), dtype=np.int32)
        self.nuc = np.zeros(n, dtype=np.int32); self.free = np.zeros(n, dtype=np.int32)
        self.co = np.zeros((n, n), dtype=np.uint16)
        self.in_pass = np.zeros(n, dtype=bool)
        self.passes = []
        self.fresh(0.0)

    def fresh(self, t):
        self.p = dict(t0=t, t_act=None, t_cond=None, drops=0, free=0, p_peak=0.0, min_margin=None)


def update(arm, G, cfg, Z, Zd, Zwall, Zref, t, dt):
    hstar = Z * (G.hq / Zwall)
    w, reach = cfg.width_fraction * G.hq, cfg.reach_fraction * G.hq
    arm.ion *= math.exp(-dt / cfg.tau_ion)
    arm.drop *= math.exp(-dt / cfg.tau_drop)
    arm.drop[arm.drop < 0.05] = 0.0
    off = np.abs(G.h - hstar)
    slab = off <= w
    off_nb = off[G.nb]
    band = (off_nb > w) & (off_nb <= w + reach)
    o = np.where(slab, (G.wt * band).sum(axis=1) / G.wsum, 0.0)
    if arm.act:
        arm.ion[slab] += cfg.alpha * o[slab] * dt
    Sg = cfg.S0 + cfg.eps * min(1.0, abs(Zd) / Zref)
    S = Sg + cfg.kappa * o
    barrier = cfg.Sc - cfg.lam * arm.ion
    p = arm.p
    if slab.any():
        m = float(np.min((barrier - S)[slab]))
        p["min_margin"] = m if p["min_margin"] is None else min(p["min_margin"], m)
    new = slab & (S >= barrier) & (arm.drop == 0)
    k = int(new.sum())
    if k:
        b = min(int(orbit_phase(Z, Zd, Zwall, Zref) * BINS / TWO_PI), BINS - 1)
        arm.drop[new] = 1.0
        arm.nuc[new] += 1
        arm.code[new, b] += 1
        free = new & (S >= cfg.Sc)
        arm.free[free] += 1
        arm.in_pass |= new
        p["drops"] += k; p["free"] += int(free.sum())
        if p["t_cond"] is None:
            p["t_cond"] = t
    live = arm.drop > 0
    P = cfg.gain * float((arm.drop[live, None] * G.wt[live] * band[live]).sum()) if live.any() else 0.0
    p["p_peak"] = max(p["p_peak"], P)
    I = float(arm.ion[slab].mean()) if slab.any() else 0.0
    if arm.act and p["t_act"] is None and I >= cfg.act_threshold:
        p["t_act"] = t


def close_pass(arm, t, kind, index):
    idx = np.flatnonzero(arm.in_pass)
    if len(idx) > 1:
        sub = arm.co[np.ix_(idx, idx)]
        arm.co[np.ix_(idx, idx)] = np.minimum(sub.astype(np.int64) + 1, 65535).astype(np.uint16)
    arm.in_pass[:] = False
    p = arm.p
    order = order_of(p["t_cond"], p["t_act"], arm.act)
    arm.passes.append(dict(arm=arm.key, index=index, t0=p["t0"], t1=t, closed_by=kind, order=order,
                           droplets=p["drops"], ion_free=p["free"], t_activation=p["t_act"], t_condensation=p["t_cond"],
                           p_peak=p["p_peak"], min_margin=p["min_margin"]))
    arm.fresh(t)


def shortcuts(arm, adj, labels, crit):
    n = len(arm.nuc)
    nuc = arm.nuc
    best = np.argmax(arm.code, axis=1)
    conc = np.divide(arm.code[np.arange(n), best], nuc, out=np.zeros(n), where=nuc > 0)
    cand = np.flatnonzero((nuc >= crit.min_nucleations) & (conc >= crit.min_concentration))
    out = []
    for x, i in enumerate(cand):
        d = None
        for j in cand[x + 1:]:
            co = int(arm.co[i, j])
            if co < crit.min_co_passes or best[i] != best[j]:
                continue
            if d is None:
                d = bfs(adj, int(i))
            hop = int(d[j]) if d[j] >= 0 else 99
            cross = labels is not None and labels[i] >= 0 and labels[j] >= 0 and labels[i] != labels[j]
            if not cross and hop < crit.min_hops:
                continue
            out.append((int(i), int(j), co, hop, bool(cross), int(best[i]), float(co * min(hop, 12))))
    out.sort(key=lambda s: (-s[6], s[0], s[1]))
    return out


def run_chamber(X, origin, normal, labels_real, labels_null, Z, Zd, times, cfg, crit, salt, path_sources,
                null_mode="axis_shuffle"):
    """Four lockstep arms over the ray trajectory. Returns plain dicts and NumPy arrays."""
    n = len(X)
    Xn = shuffle_axes(X, salt) if null_mode == "axis_shuffle" else height_preserving_shuffle(X, origin, normal, salt)
    geo = {"real": _Geometry(X, origin, normal, cfg.k), "null": _Geometry(Xn, origin, normal, cfg.k)}
    adjs = {e: adjacency(g.nb) for e, g in geo.items()}
    arms = [_Arm(key, emb, act, n) for key, emb, act in ARMS]
    Zwall = float(np.max(np.abs(Z))) or 1.0
    Zref = float(np.max(np.abs(Zd))) or 1.0
    index = 0
    for s in range(1, len(times)):
        dt = float(times[s] - times[s - 1])
        for a in arms:
            update(a, geo[a.emb], cfg, float(Z[s]), float(Zd[s]), Zwall, Zref, float(times[s]), dt)
        kind = splice_kind(Z[s - 1], Zd[s - 1], Z[s], Zd[s])
        if kind:
            index += 1
            for a in arms:
                close_pass(a, float(times[s]), kind, index)
    rng = np.random.default_rng(salt)
    sources = np.sort(rng.choice(n, size=min(path_sources, n), replace=False))
    labels = {"real": labels_real, "null": labels_null}
    stats, found = [], []
    base = {e: (clustering(adjs[e]), *path_stats(adjs[e], sources)) for e in adjs}
    for a in arms:
        sc = shortcuts(a, adjs[a.emb], labels[a.emb], crit)
        aug = [set(s) for s in adjs[a.emb]]
        for i, j, *_ in sc:
            aug[i].add(j); aug[j].add(i)
        c0, l0, u0, e0 = base[a.emb]
        c1 = clustering(aug); l1, u1, e1 = path_stats(aug, sources)
        stats.append(dict(arm=a.key, passes=len(a.passes), anomalous_passes=sum(p["order"] in ("cond-off", "cond-noact", "cond-first") for p in a.passes),
                          droplets=int(a.nuc.sum()), ion_free=int(a.free.sum()), sparsity=float(np.mean(a.code == 0)),
                          shortcut_count=len(sc),
                          small_world=dict(clustering=c0, path_length=l0, unreachable_fraction=u0, efficiency=e0,
                                           clustering_with_shortcuts=c1, path_length_with_shortcuts=l1,
                                           unreachable_fraction_with_shortcuts=u1, efficiency_with_shortcuts=e1)))
        found.append((a.key, sc[:crit.max_reported]))
    return dict(h_scale=geo["real"].hq, arms=arms, stats=stats, shortcuts=found,
                sparse=np.stack([a.code for a in arms]).astype(np.int32),
                nucleations=np.stack([a.nuc for a in arms]).astype(np.int32),
                free=np.stack([a.free for a in arms]).astype(np.int32))
