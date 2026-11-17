"""Barrier Lyapunov bracket control (pure math). Derivation and discrete-invariance proof: docs/pipelines/PROBE.md."""

from __future__ import annotations

import math

from .contracts import Bracket, BracketState, BracketStep


def bracket_state(b: Bracket, value: float) -> BracketState:
    """Barrier value and wall proximity of a coordinate.

    >>> s = bracket_state(Bracket(lo=-1, hi=1), 0.0); (s.barrier, s.fraction, s.at_wall)
    (0.0, 0.0, False)
    """
    kb, e = b.half_width, value - b.center
    frac = min(1.0, abs(e) / kb)
    if abs(e) >= kb:
        raise ValueError("value is outside the bracket")
    V = 0.5 * math.log(kb * kb / (kb * kb - e * e))
    return BracketState(value=value, error=e, barrier=V, fraction=frac, at_wall=abs(e) >= (1 - b.margin) * kb - 1e-12)


def _flow(e: float, v: float, h: float, kb: float) -> float:
    """Exact flow of de/dt = v (1 - e^2/kb^2) outward and de/dt = v inward, over time h."""
    if v == 0 or h == 0:
        return e
    if e * v < 0:                                   # inward: unscaled until the centre
        t0 = abs(e) / abs(v)
        if h <= t0:
            return e + v * h
        e, h = 0.0, h - t0
    return kb * math.tanh(math.atanh(e / kb) + v * h / kb)   # outward: never reaches kb


def bracket_step(b: Bracket, value: float, velocity: float, dt: float) -> BracketStep:
    """Filter a human move so the coordinate can never leave the bracket.

    Outward motion follows the exact solution e(t) = k_b tanh(atanh(e0/k_b) + v t / k_b); inward requests pass
    unscaled; the optional centring gain is applied by operator splitting as exponential decay, which only shrinks |e|.
    A final clamp keeps |e| <= (1 - margin) k_b against rounding.

    >>> s = bracket_step(Bracket(lo=0, hi=1), value=0.8, velocity=-0.2, dt=1.0)
    >>> round(s.value, 6), s.substeps
    (0.6, 1)
    """
    if not math.isfinite(velocity) or not math.isfinite(dt) or dt < 0:
        raise ValueError("finite velocity and non-negative dt required")
    if not b.contains(value):
        raise ValueError("value starts outside the bracket")
    kb, c = b.half_width, b.center
    limit = (1 - max(b.margin, 1e-9)) * kb
    e = max(-limit, min(limit, value - c))
    n = 1 if b.gain == 0 else min(1000, max(1, math.ceil(b.gain * dt / 0.1)))
    h = dt / n
    for _ in range(n):
        e = _flow(e, velocity, h, kb)
        e = max(-limit, min(limit, e))
        if b.gain:
            e *= math.exp(-b.gain * h)
    new = c + e
    return BracketStep(value=new, requested_velocity=velocity, applied_displacement=new - value, substeps=n,
                       state=bracket_state(b, new))
