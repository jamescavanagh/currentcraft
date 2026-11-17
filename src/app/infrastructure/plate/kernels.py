"""Numeric kernels for the plate slice. Infrastructure only.

The three-body loop uses plain floats (three bodies: Python scalars beat tiny NumPy arrays per step);
recordings and the plate field are NumPy. Design source: docs/pipelines/PLATE_ISOSCELES.md.
"""

from __future__ import annotations

import math

import numpy as np

TWO_PI = 2.0 * math.pi
J = np.array([[0.0, -1.0], [1.0, 0.0]])


# ------------------------------------------------------------------ three-body

def initial_state(side_mass, object_mass, side_radius, spin_factor, zeta0, zeta_dot0):
    """COM-frame spatial isosceles start. Returns (positions[3][3], velocities[3][3], masses[3])."""
    m, m3, r = side_mass, object_mass, side_radius
    vc = math.sqrt(r * (m / (4 * r * r) + m3 * r / (r * r + zeta0 * zeta0) ** 1.5))
    M = 2 * m + m3
    zA = -m3 * zeta0 / M
    wO = zA + zeta0
    vzA = -m3 * zeta_dot0 / M
    vzO = vzA + zeta_dot0
    pos = [[r, 0.0, zA], [-r, 0.0, zA], [0.0, 0.0, wO]]
    vel = [[0.0, spin_factor * vc, vzA], [0.0, -spin_factor * vc, vzA], [0.0, 0.0, vzO]]
    return pos, vel, [m, m, m3]


def accelerations(pos, mass, eps2):
    a = [[0.0, 0.0, 0.0] for _ in range(3)]
    for i in range(3):
        pi = pos[i]
        for j in range(i + 1, 3):
            pj = pos[j]
            dx, dy, dz = pj[0] - pi[0], pj[1] - pi[1], pj[2] - pi[2]
            d2 = dx * dx + dy * dy + dz * dz + eps2
            inv = 1.0 / (d2 * math.sqrt(d2))
            fi, fj = mass[j] * inv, mass[i] * inv
            a[i][0] += fi * dx; a[i][1] += fi * dy; a[i][2] += fi * dz
            a[j][0] -= fj * dx; a[j][1] -= fj * dy; a[j][2] -= fj * dz
    return a


def verlet_step(pos, vel, mass, acc, dt, eps2):
    """One velocity-Verlet step (symplectic, time-reversible). Mutates pos and vel; returns new accelerations."""
    h = 0.5 * dt
    for i in range(3):
        for k in range(3):
            vel[i][k] += h * acc[i][k]
            pos[i][k] += dt * vel[i][k]
    acc = accelerations(pos, mass, eps2)
    for i in range(3):
        for k in range(3):
            vel[i][k] += h * acc[i][k]
    return acc


def energy(pos, vel, mass, eps2):
    e = sum(0.5 * mass[i] * (vel[i][0] ** 2 + vel[i][1] ** 2 + vel[i][2] ** 2) for i in range(3))
    for i in range(3):
        for j in range(i + 1, 3):
            d2 = sum((pos[j][k] - pos[i][k]) ** 2 for k in range(3))
            e -= mass[i] * mass[j] / math.sqrt(d2 + eps2)
    return e


def angular_momentum_z(pos, vel, mass):
    return sum(mass[i] * (pos[i][0] * vel[i][1] - pos[i][1] * vel[i][0]) for i in range(3))


def mirror_error(pos):
    A, B, O = pos
    return max(math.hypot(A[0] + B[0], A[1] + B[1]), abs(A[2] - B[2]), math.hypot(O[0], O[1]))


def recentre(pos, vel, mass):
    M = sum(mass)
    for k in range(3):
        cp = sum(mass[i] * pos[i][k] for i in range(3)) / M
        cv = sum(mass[i] * vel[i][k] for i in range(3)) / M
        for i in range(3):
            pos[i][k] -= cp
            vel[i][k] -= cv


def readout(pos, vel, mass, phase, eps2):
    A, O = pos[0], pos[2]
    r = math.hypot(A[0], A[1])
    omega = (A[0] * vel[0][1] - A[1] * vel[0][0]) / (r * r)
    height = 0.5 * (pos[0][2] + pos[1][2])
    zeta = O[2] - height
    zeta_dot = vel[2][2] - 0.5 * (vel[0][2] + vel[1][2])
    return [height, phase, omega, r, angular_momentum_z(pos, vel, mass), zeta, zeta_dot, energy(pos, vel, mass, eps2),
            mirror_error(pos)]


def run_isosceles(*, side_mass, object_mass, side_radius, spin_factor, zeta0, zeta_dot0, softening, dt, steps,
                  record_every, mass_events=(), escape_zeta=9.0, escape_radius=6.0):
    """Integrate with live mass events and crossing detection. Returns a dict of NumPy recordings and lists."""
    eps2 = softening * softening
    pos, vel, mass = initial_state(side_mass, object_mass, side_radius, spin_factor, zeta0, zeta_dot0)
    acc = accelerations(pos, mass, eps2)
    t, phase = 0.0, 0.0
    theta_prev = math.atan2(pos[0][1], pos[0][0])
    events = list(mass_events)  # [(t, mass)]
    applied = []
    E0, L0 = energy(pos, vel, mass, eps2), angular_momentum_z(pos, vel, mass)
    max_e = max_l = max_mirror = 0.0
    rec_t, rec_p, rec_v, rec_m, rec_r = [], [], [], [], []
    crossings = []
    zeta_prev = pos[2][2] - 0.5 * (pos[0][2] + pos[1][2])
    status, n = "ok", 0

    def record():
        nonlocal max_e, max_l, max_mirror
        ro = readout(pos, vel, mass, phase, eps2)
        rec_t.append(t); rec_p.append([p[:] for p in pos]); rec_v.append([v[:] for v in vel]); rec_m.append(mass[:])
        rec_r.append(ro)
        max_e = max(max_e, abs(ro[7] - E0) / abs(E0)) if E0 != 0 else max_e
        max_l = max(max_l, abs(ro[4] - L0))
        max_mirror = max(max_mirror, ro[8])

    record()
    while n < steps:
        if events and t >= events[0][0] - 1e-12:
            et, em = events.pop(0)
            mass[2] = em
            recentre(pos, vel, mass)
            acc = accelerations(pos, mass, eps2)
            E0, L0 = energy(pos, vel, mass, eps2), angular_momentum_z(pos, vel, mass)
            applied.append(et)
            zeta_prev = pos[2][2] - 0.5 * (pos[0][2] + pos[1][2])
        acc = verlet_step(pos, vel, mass, acc, dt, eps2)
        t_prev, t, n = t, t + dt, n + 1
        theta = math.atan2(pos[0][1], pos[0][0])
        d = theta - theta_prev
        d -= TWO_PI * round(d / TWO_PI)
        phase += d
        theta_prev = theta
        height = 0.5 * (pos[0][2] + pos[1][2])
        zeta = pos[2][2] - height
        if zeta_prev != 0 and zeta != 0 and (zeta > 0) != (zeta_prev > 0):
            f = zeta_prev / (zeta_prev - zeta)
            crossings.append(dict(index=len(crossings), t=t_prev + f * dt, direction=1 if zeta > 0 else -1,
                                  side_after="+" if zeta > 0 else "-", plate_height=height, plate_phase=phase,
                                  radial_offset=math.hypot(pos[2][0], pos[2][1])))
        if zeta != 0:
            zeta_prev = zeta
        r = math.hypot(pos[0][0], pos[0][1])
        if abs(zeta) > escape_zeta or r > escape_radius:
            status = "escaped"
            record()
            break
        if n % record_every == 0:
            record()
    if rec_t[-1] != t:
        record()
    return dict(times=np.array(rec_t), positions=np.array(rec_p), velocities=np.array(rec_v), masses=np.array(rec_m),
                plate=np.array(rec_r), crossings=crossings, applied=applied, status=status, steps_run=n, t_end=t,
                max_e=max_e, max_l=max_l, max_mirror=max_mirror)


# ------------------------------------------------------------------ plate field

def _rot(theta):
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s], [s, c]])


def plate_field(points, vortices, delta):
    """Rosenhead-Moore vortices in the plate frame. points (K,2), vortices (V,3: u, v, Gamma) -> vel (K,2), jac (K,2,2)."""
    p = np.asarray(points, dtype=np.float64)
    vel = np.zeros_like(p)
    jac = np.zeros((len(p), 2, 2))
    eye = np.eye(2)
    for u, v, g in np.asarray(vortices, dtype=np.float64).reshape(-1, 3):
        d = p - np.array([u, v])
        s = np.sum(d * d, axis=1) + delta * delta
        c = g / (TWO_PI * s)
        vel += c[:, None] * (d @ J.T)
        dk = eye[None] / s[:, None, None] - 2 * d[:, :, None] * d[:, None, :] / (s * s)[:, None, None]
        jac += (g / TWO_PI) * np.einsum("ij,kjl->kil", J, dk)
    return vel, jac


def field_in_frame(points, vortices, delta, frame="plate", omega=0.0, phase=0.0):
    if frame == "plate":
        return plate_field(points, vortices, delta)
    R = _rot(phase)
    x = np.asarray(points, dtype=np.float64)
    vp, jp = plate_field(x @ R, vortices, delta)  # R^T x for each row
    vel = omega * (x @ J.T) + vp @ R.T
    jac = omega * J[None] + np.einsum("ij,kjl,ml->kim", R, jp, R)
    return vel, jac


def point_arc_distance(q, c, radius, a, b):
    """Exact distance from point q to the circular arc of the given centre and radius from angle a to b (b > a)."""
    dx, dy = q[0] - c[0], q[1] - c[1]
    rho = math.hypot(dx, dy)
    if rho == 0.0:
        return radius
    alpha = math.atan2(dy, dx)
    if (alpha - a) % TWO_PI <= (b - a):
        return abs(rho - radius)
    pa = (c[0] + radius * math.cos(a), c[1] + radius * math.sin(a))
    pb = (c[0] + radius * math.cos(b), c[1] + radius * math.sin(b))
    return min(math.hypot(q[0] - pa[0], q[1] - pa[1]), math.hypot(q[0] - pb[0], q[1] - pb[1]))


def ring_samples_and_bounds(vortices, delta, center, radius, samples, frame="plate", omega=0.0, phase=0.0):
    """Ring velocities, angles and whole-segment bounds B_e >= sup ||du/ds|| (docs/pipelines/PLATE_ISOSCELES.md)."""
    phi = TWO_PI * np.arange(samples) / samples
    pts = np.c_[center[0] + radius * np.cos(phi), center[1] + radius * np.sin(phi)]
    vel, _ = field_in_frame(pts, vortices, delta, frame, omega, phase)
    vs = np.asarray(vortices, dtype=np.float64).reshape(-1, 3)
    if frame == "inertial":
        R = _rot(phase)
        locs = vs[:, :2] @ R.T
    else:
        locs = vs[:, :2]
    ends = np.r_[phi[1:], phi[0] + TWO_PI]
    bound = np.full(samples, abs(omega) if frame == "inertial" else 0.0)
    for (x, y), g in zip(locs, vs[:, 2]):
        for e in range(samples):
            d = point_arc_distance((x, y), center, radius, phi[e], ends[e])
            bound[e] += abs(g) / (TWO_PI * (d * d + delta * delta))
    return vel, phi, bound
