"""numpy kernels for the HFGT capability graph. Boolean incidence products only; no dynamics.

place(l, y) = sigma(B_S) * index(l) + index(y)   rows of the matricized incidence tensor
M-[place, e] = 1 when capability e pulls operand l from buffer y; M+ likewise for injects
W = M+^T M-   witnesses per ordered pair; A_rho = (W > 0) * a a^T, diagonal moved to a node feature
"""
from __future__ import annotations

import numpy as np


def incidence(caps):
    """Return (operands L, buffers B, places, M-, M+) for capability records in canonical order."""
    L = sorted({op for c in caps for op, _ in c.pulls + c.injects})
    B = sorted({y for c in caps for _, y in c.pulls + c.injects})
    row = {(l, y): i for i, (l, y) in enumerate((l, y) for l in L for y in B)}
    n = len(caps)
    Mm = np.zeros((len(row), n), np.int64)
    Mp = np.zeros((len(row), n), np.int64)
    for k, c in enumerate(caps):
        for p in c.pulls:
            Mm[row[p], k] = 1
        for p in c.injects:
            Mp[row[p], k] = 1
    places = sorted(row, key=row.get)
    return L, B, places, Mm, Mp


def sequences(Mm, Mp, avail):
    """W = M+^T M-; A = Boolean, masked by availability; returns (W, A without diagonal, self-sequence flags)."""
    W = Mp.T @ Mm
    a = np.asarray(avail, np.int64)
    A = (W > 0).astype(np.int64) * a[:, None] * a[None, :]
    self_seq = np.diag(A).copy()
    np.fill_diagonal(A, 0)
    return W, A, self_seq


def five_rule(caps):
    """The paper's construction (I or II or III or IV) and V, buffers standing in for transformation resources.
    An independent oracle for A_rho: it never touches the incidence product."""
    n = len(caps)
    out = np.zeros((n, n), np.int64)
    tl = [c.capability_class in ("transform", "control") for c in caps]
    ib = [frozenset(y for _, y in c.pulls) for c in caps]
    ob = [frozenset(y for _, y in c.injects) for c in caps]
    ins = [frozenset(l for l, _ in c.pulls) for c in caps]
    outs = [frozenset(l for l, _ in c.injects) for c in caps]
    for a in range(n):
        for b in range(n):
            if a == b:
                continue
            same = ob[a] == ib[b]
            I = tl[a] and tl[b] and same
            II = tl[a] and not tl[b] and same
            III = (not tl[a]) and tl[b] and same
            IV = (not tl[a]) and (not tl[b]) and same
            V = bool(outs[a] & ins[b])
            out[a, b] = int((I or II or III or IV) and V)
    return out


def reachable(A, sources, targets):
    """Breadth-first reachability on a dense Boolean adjacency matrix."""
    seen = set(int(s) for s in sources)
    frontier = list(seen)
    while frontier:
        nxt = [int(j) for i in frontier for j in np.nonzero(A[i])[0] if int(j) not in seen]
        seen.update(nxt)
        frontier = nxt
    return any(int(t) in seen for t in targets)
