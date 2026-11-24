"""Numerical kernels for the procedural vortex field (same field as the labeling bench; not CFD).

    k_ij = g_j / (2 pi (r^2 + softening)) / N * scale
    u = sum_j(-k dy - inflow |k| dx),   v = sum_j(k dx - inflow |k| dy)
"""

from __future__ import annotations

import math

import numpy as np


def field(V: np.ndarray, x: np.ndarray, y: np.ndarray, inflow: float, softening: float, scale: float):
    """Velocity (u, v) and analytic Jacobian (ux, uy, vx, vy) at points (x, y)."""
    N = len(V)
    dx = x[..., None] - V[:, 0]
    dy = y[..., None] - V[:, 1]
    r2 = dx * dx + dy * dy + softening
    k = V[:, 2] / (2 * math.pi * r2) / N * scale
    a, s = np.abs(k), np.sign(k)
    kx, ky = -k * 2 * dx / r2, -k * 2 * dy / r2
    ax, ay = s * kx, s * ky
    u = np.sum(-k * dy - inflow * a * dx, -1)
    v = np.sum(k * dx - inflow * a * dy, -1)
    ux = np.sum(-kx * dy - inflow * (ax * dx + a), -1)
    uy = np.sum(-(ky * dy + k) - inflow * ay * dx, -1)
    vx = np.sum(kx * dx + k - inflow * ax * dy, -1)
    vy = np.sum(ky * dx - inflow * (ay * dy + a), -1)
    return u, v, ux, uy, vx, vy


def coupling(V: np.ndarray, softening: float, scale: float) -> np.ndarray:
    dx = V[:, None, 0] - V[None, :, 0]
    dy = V[:, None, 1] - V[None, :, 1]
    k = V[None, :, 2] / (2 * math.pi * (dx * dx + dy * dy + softening)) / len(V) * scale
    np.fill_diagonal(k, 0.0)
    return k


def grid_xy(size: int, extent: float):
    xs = np.linspace(-extent, extent, size)
    X, Y = np.meshgrid(xs, xs[::-1])  # row 0 = +extent
    return X, Y


def channels(V, inflow, size, extent, softening, scale) -> np.ndarray:
    X, Y = grid_xy(size, extent)
    u, v, ux, uy, vx, vy = field(V, X, Y, inflow, softening, scale)
    return np.stack([u, v, vx - uy, ux + vy, np.hypot(u, v)])


def _seed_coordinates(points):
    """Validate internal seed coordinates without echoing source values."""
    try:
        if isinstance(points, (list, tuple)) and points and isinstance(points[0], dict):
            xy = np.array([[q["x"], q["y"]] for q in points], dtype=np.float64)
        else:
            xy = np.asarray(points, dtype=np.float64)
        if xy.shape == (0,):
            xy = xy.reshape(0, 2)
        if xy.ndim != 2 or xy.shape[1] != 2 or not np.isfinite(xy).all():
            raise ValueError
    except (TypeError, ValueError, KeyError, OverflowError):
        raise ValueError("Newton seeds must be finite coordinate pairs") from None
    return xy


def critical_points(V, inflow, softening, scale, seeds=40, extent=2.0, iters=40,
                    warm_starts=None, seed_points=None):
    """Solve from a grid (or explicit internal test seeds) plus warm coordinates.

    Warm starts are re-solved and revalidated, never copied into the result.
    No completeness or disappearance certification is implied.
    """
    if seed_points is None:
        xs = np.linspace(-extent, extent, seeds)
        X, Y = np.meshgrid(xs, xs)
        xy = np.column_stack((X.ravel(), Y.ravel()))
    else:
        xy = _seed_coordinates(seed_points)
        if not len(xy):
            raise ValueError("Newton seed set must not be empty")
    if warm_starts is not None:
        xy = np.concatenate((xy, _seed_coordinates(warm_starts)), axis=0)
    x, y = xy[:, 0].copy(), xy[:, 1].copy()
    for _ in range(iters):
        u, v, ux, uy, vx, vy = field(V, x, y, inflow, softening, scale)
        det = ux * vy - uy * vx
        det = np.where(np.abs(det) < 1e-12, 1e-12, det)
        dx, dy = (vy * u - uy * v) / det, (-vx * u + ux * v) / det
        f = np.minimum(1, 0.15 / np.maximum(np.hypot(dx, dy), 1e-12))
        x, y = np.clip(x - dx * f, -3 * extent / 2, 3 * extent / 2), np.clip(y - dy * f, -3 * extent / 2, 3 * extent / 2)
    u, v, ux, uy, vx, vy = field(V, x, y, inflow, softening, scale)
    ok = (np.hypot(u, v) < 1e-9) & (np.abs(x) < extent) & (np.abs(y) < extent)
    pts: list[dict] = []
    for i in np.flatnonzero(ok):
        if any(math.hypot(x[i] - q["x"], y[i] - q["y"]) < 1e-3 for q in pts):
            continue
        det, tr = float(ux[i] * vy[i] - uy[i] * vx[i]), float(ux[i] + vy[i])
        if det < 0:
            kind = "saddle"
        elif inflow < 1e-9:
            kind = "centre"
        elif tr > 0:
            kind = "source"
        else:
            kind = "spiral_sink" if tr * tr < 4 * det else "node_sink"
        disc = math.sqrt(max(0.0, tr * tr - 4 * det))
        # eigenvalues of J are mu (lambda is reserved for inflow)
        mu = min(abs((tr + disc) / 2), abs((tr - disc) / 2)) if det < 0 else None
        pts.append({"x": float(x[i]), "y": float(y[i]), "kind": kind, "det": det, "trace": tr, "mu_min_abs": mu})
    pts.sort(key=lambda q: (q["kind"] != "saddle", -q["y"], q["x"]))
    return pts


def saddle_count(V, inflow, softening, scale, seeds=40, extent=2.0,
                 warm_starts=None, seed_points=None) -> int:
    return sum(1 for q in critical_points(V, inflow, softening, scale, seeds, extent,
                                         warm_starts=warm_starts, seed_points=seed_points)
               if q["kind"] == "saddle")


def collisions(V, inflows, counts, softening, scale, seeds=40, extent=2.0, refine=7,
               slice_points=None, seed_points=None):
    """Estimate changed-count event locations using both endpoint root sets.

    Counts are numerical observations, not certified topology. Equal-count
    intervals can hide events, and multi-count brackets can contain several.
    """
    if len(inflows) != len(counts) or (slice_points is not None and len(slice_points) != len(inflows)):
        raise ValueError("Inconsistent event bracket lengths")
    if any(b <= a for a, b in zip(inflows, inflows[1:])):
        raise ValueError("Event inflows must be strictly increasing")
    out = []
    for i in range(len(inflows) - 1):
        if counts[i] != counts[i + 1]:
            lo, hi, c0 = inflows[i], inflows[i + 1], counts[i]
            if slice_points is None:
                left = critical_points(V, lo, softening, scale, seeds, extent, seed_points=seed_points)
                right = critical_points(V, hi, softening, scale, seeds, extent,
                                        warm_starts=left, seed_points=seed_points)
            else:
                left, right = slice_points[i], slice_points[i + 1]
            if [sum(q["kind"] == "saddle" for q in pts) for pts in (left, right)] != list(counts[i:i + 2]):
                raise ValueError("Unresolved event endpoint recovery")
            for _ in range(refine):
                m = (lo + hi) / 2
                warm = np.concatenate((_seed_coordinates(left), _seed_coordinates(right)), axis=0)
                mid = critical_points(V, m, softening, scale, seeds, extent,
                                      warm_starts=warm, seed_points=seed_points)
                cm = sum(q["kind"] == "saddle" for q in mid)
                if not min(counts[i:i + 2]) <= cm <= max(counts[i:i + 2]):
                    raise ValueError("Unresolved event midpoint recovery")
                if cm == c0:
                    lo, left = m, mid
                else:
                    hi, right = m, mid
            out.append(((lo + hi) / 2, counts[i], counts[i + 1]))
    return out


def advect(V, x, y, inflow, softening, scale, steps, step_length, every, on_record=None):
    """Move tracers along the field with capped step length; call ``on_record(x, y, step)`` every k steps."""
    x, y = x.astype(np.float64).copy(), y.astype(np.float64).copy()
    for s in range(1, steps + 1):
        u, v, *_ = field(V, x, y, inflow, softening, scale)
        n = np.hypot(u, v) + 1e-12
        dt = np.minimum(step_length / n, 1.5)
        x += u * dt
        y += v * dt
        if on_record is not None and (s % every == 0 or s == steps):
            on_record(x, y, s)
    return x, y
