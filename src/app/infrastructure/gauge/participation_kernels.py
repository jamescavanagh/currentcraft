"""Participation null kernels.

Curveball trades swap non-shared processes between two resources inside one stage, so every
resource's and every process's degree per stage is preserved and no edge crosses a stage.
Rewiring breaks *who* co-participates while keeping stage structure: it tests the local score
against stage-matched chance. It cannot test locality (both scores lose signal together), so the
local-vs-global difference is tested by a paired, stage-stratified bootstrap instead.
"""

from __future__ import annotations

import numpy as np


def ranks(x: np.ndarray) -> np.ndarray:
    """1-based average ranks (ties share the mean rank)."""
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    cum = np.cumsum(counts)
    return (cum - (counts - 1) / 2.0)[inv]


def auc(score: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """(AUC, weight = n_pos * n_neg); weight 0 when a class is missing."""
    npos = int(y.sum())
    nneg = len(y) - npos
    if npos == 0 or nneg == 0:
        return 0.5, 0.0
    r = ranks(score)
    return float((r[y == 1].sum() - npos * (npos + 1) / 2.0) / (npos * nneg)), float(npos * nneg)


def stratified_auc(score: np.ndarray, y: np.ndarray, groups: list[np.ndarray]) -> float:
    """Weighted mean of per-stage AUCs (weights n_pos * n_neg); 0.5 if no stage has both labels."""
    tot = w = 0.0
    for g in groups:
        a, wt = auc(score[g], y[g])
        tot += a * wt
        w += wt
    return tot / w if w else 0.5


def curveball(stage_sets: dict[str, dict[str, set[str]]], rng: np.random.Generator, trades_per_node: int):
    """One stage-preserving rewiring. Returns a new {stage: {resource: set(process)}}."""
    out = {}
    for stage, sets in stage_sets.items():
        res = sorted(sets)
        cur = {r: set(sets[r]) for r in res}
        if len(res) >= 2:
            for _ in range(trades_per_node * len(res)):
                i, j = rng.choice(len(res), size=2, replace=False)
                A, B = cur[res[i]], cur[res[j]]
                a_only, b_only = sorted(A - B), sorted(B - A)
                if not a_only or not b_only:
                    continue
                pool = a_only + b_only
                rng.shuffle(pool)
                shared = A & B
                cur[res[i]] = shared | set(pool[: len(a_only)])
                cur[res[j]] = shared | set(pool[len(a_only):])
        out[stage] = cur
    return out


def labels(stage_sets, a: list[str], b: list[str], st: list[str]) -> np.ndarray:
    empty: set[str] = set()
    return np.array([int(bool(stage_sets.get(s, {}).get(x, empty) & stage_sets.get(s, {}).get(z, empty)))
                     for x, z, s in zip(a, b, st)], dtype=np.int64)
