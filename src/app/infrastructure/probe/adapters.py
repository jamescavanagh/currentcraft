"""Numpy adapters for the probe ports."""

from __future__ import annotations

import math
from collections import Counter

import numpy as np

from app.application.probe.barrier import bracket_state
from app.application.probe.contracts import (SLAB_COORDS_SPEC, POSITIONS_SPEC, CandidateCluster, CandidateRequest,
                                             CandidateSet, FieldReading, LensReading, LensRecord, LensRequest,
                                             PairCandidate, PlaneReading, ProbeReading, ProbeRequest, RingReading,
                                             SpinGauges, StateReading, TermWeight)
from app.application.enrichment.contracts import ARMS
from app.infrastructure.gauge.winding import measure_velocity_winding
from app.infrastructure.plate import kernels as PK

from . import kernels as K


class _Pose:
    """Everything derived from a probe request once: frame, slab, aperture membership, vortices."""

    def __init__(self, store, req: ProbeRequest):
        c, p, a = req.cloud, req.pose, req.aperture
        self.req = req
        self.X = store.get(c.positions)
        self.ne, self.eu, self.ev = K.plate_frame(p.normal, p.tilt_deg, p.yaw_deg, p.phase)
        self.mask, uv = K.slab(self.X, p.origin, self.ne, self.eu, self.ev, p.offset, p.slab_half_width)
        self.slab_idx = np.flatnonzero(self.mask)
        self.uv = uv[self.slab_idx]
        d = np.linalg.norm(self.uv - np.asarray(a.center), axis=1)
        order = np.argsort(d, kind="stable")
        inside = order[d[order] <= a.radius]
        self.ap_local = inside                              # indices into slab arrays
        self.ap_idx = self.slab_idx[inside]                 # indices into cloud
        strength = {s.id: s.strength for s in c.strengths}
        ids = c.ids
        self.vort = np.array([[*self.uv[k], strength[ids[i]]] for k, i in enumerate(self.slab_idx) if ids[i] in strength]).reshape(-1, 3)
        self.vort_in = np.array([strength[ids[i]] for i in self.ap_idx if ids[i] in strength])
        self.texts = {t.id: t for t in c.texts}

    def field(self, pts):
        p = self.req.pose
        frame = self.req.frame
        return PK.field_in_frame(pts, self.vort, self.req.core_radius, frame, p.omega if frame == "inertial" else 0.0, 0.0)


class NumpyProbeAdapter:
    def __init__(self, store):
        self.store = store

    def measure(self, req: ProbeRequest) -> ProbeReading:
        P = _Pose(self.store, req)
        a, c = req.aperture, req.cloud
        cx, cy = a.center
        phi = TWO_PI_SAMPLES(a.ring_samples)
        ring = np.c_[cx + a.radius * np.cos(phi), cy + a.radius * np.sin(phi)]
        vel, jac = P.field(ring)
        circ, eta, leak, masks = K.ring_readings(vel, jac, phi, a.radius, req.gradient_floor, req.speed_floor)
        omega = req.pose.omega if req.frame == "inertial" else 0.0
        _, _, bound = PK.ring_samples_and_bounds(P.vort, req.core_radius, a.center, a.radius, a.ring_samples,
                                                 req.frame, omega, 0.0)
        w = measure_velocity_winding(vel, phi, a.radius, derivative_bound=bound,
                                     bound_provenance="analytic whole-arc bound, regularised vortices at slab records")
        # field grid inside the aperture
        g = np.linspace(-a.radius, a.radius, a.grid)
        gx, gy = np.meshgrid(g + cx, g + cy)
        pts = np.c_[gx.ravel(), gy.ravel()]
        pts = pts[np.linalg.norm(pts - np.asarray(a.center), axis=1) <= a.radius]
        fv, fj = P.field(pts)
        speed = np.linalg.norm(fv, axis=1)
        ok = speed > req.speed_floor
        vort = fj[:, 1, 0] - fj[:, 0, 1]
        S = 0.5 * (fj + np.transpose(fj, (0, 2, 1)))
        strain = np.sqrt(np.sum(S * S, axis=(1, 2)))
        field = FieldReading(mean_vorticity=float(vort[ok].mean()) if ok.any() else None,
                             mean_strain=float(strain[ok].mean()) if ok.any() else None,
                             max_speed=float(speed.max()) if len(speed) else 0.0,
                             unmasked_fraction=float(ok.mean()) if len(ok) else 0.0)
        # plane
        Y = P.X[P.ap_idx]
        plane = PlaneReading(n_used=len(Y), valid=False, planarity=None, tilt_to_plate_deg=None)
        if len(Y) >= 3:
            ev, vec = np.linalg.eigh(np.cov((Y - Y.mean(0)).T))
            if ev[1] > 1e-15:
                ln = vec[:, 0]
                plane = PlaneReading(n_used=len(Y), valid=True, planarity=float(1 - ev[0] / ev[1]),
                                     tilt_to_plate_deg=float(math.degrees(math.acos(min(1.0, abs(float(ln @ P.ne)))))))
        # states
        ids = c.ids
        in_ap = len(P.ap_idx)
        slab_r = float(np.max(np.linalg.norm(P.uv, axis=1))) if len(P.uv) else 0.0
        dens = None
        if in_ap and slab_r > 0:
            dens = (in_ap / (math.pi * a.radius ** 2)) / (len(P.slab_idx) / (math.pi * slab_r ** 2))
        condensed = None
        if c.enrichment is not None:
            nuc = self.store.get(c.enrichment.nucleations)[ARMS.index(c.enrichment_arm)]
            condensed = int(np.sum(nuc[P.ap_idx] > 0))
        labelled = set(c.labelled_ids)
        states = StateReading(total=len(ids), in_slab=len(P.slab_idx), in_aperture=in_ap,
                              with_strength=len(P.vort_in), condensed=condensed,
                              labelled=sum(ids[i] in labelled for i in P.ap_idx), density_ratio=dens)
        gp, gn = float(P.vort_in[P.vort_in > 0].sum()), float(-P.vort_in[P.vort_in < 0].sum())
        spin = SpinGauges(global_spin=req.pose.omega,
                          local_spin=None if field.mean_vorticity is None else 0.5 * field.mean_vorticity,
                          positive_circulation=gp, negative_circulation=gn,
                          balance=None if gp + gn == 0 else (gp - gn) / (gp + gn))
        ring_r = RingReading(circulation=circ, eta_kin=eta, leakage=leak, winding_status=w.status,
                             sampled_index=w.sampled_index, certified_index=w.certified_index,
                             masks=tuple(masks) + tuple(w.reasons))
        return ProbeReading(request_digest=req.digest(), effective_normal=tuple(map(float, P.ne)),
                            axis_u=tuple(map(float, P.eu)), axis_v=tuple(map(float, P.ev)),
                            offset_state=bracket_state(req.offset_bracket, req.pose.offset),
                            radius_state=bracket_state(req.radius_bracket, a.radius),
                            ring=ring_r, field=field, plane=plane, states=states, spin=spin,
                            aperture_ids=tuple(ids[i] for i in P.ap_idx),
                            slab_ids=tuple(ids[i] for i in P.slab_idx),
                            slab_coords=self.store.put(SLAB_COORDS_SPEC, np.ascontiguousarray(P.uv, dtype=np.float64),
                                                       producer="NumpyProbeAdapter"))


def TWO_PI_SAMPLES(k):
    return 2 * math.pi * np.arange(k) / k


def _counts(P, local_idx):
    out = Counter()
    for k in local_idx:
        t = P.texts.get(P.req.cloud.ids[P.slab_idx[k]])
        if t is not None:
            out.update(K.words(t.title, t.text))
    return out


class NumpyLensAdapter:
    def __init__(self, store):
        self.store = store

    def lens(self, req: LensRequest) -> LensReading:
        P = _Pose(self.store, req.probe)
        ids = req.probe.cloud.ids
        lr = req.probe.aperture.radius / req.magnification
        d = np.linalg.norm(P.uv - np.asarray(req.pointer), axis=1)
        order = np.argsort(d, kind="stable")
        under = [int(k) for k in order if d[k] <= lr]
        lab = set(req.probe.cloud.labelled_ids)

        def rec(k):
            i = ids[P.slab_idx[k]]
            t = P.texts.get(i)
            return LensRecord(id=i, title=t.title if t else None, distance=float(d[k]), u=float(P.uv[k, 0]),
                              v=float(P.uv[k, 1]), labelled=i in lab)
        records = tuple(rec(k) for k in under)
        slab_counts = _counts(P, range(len(P.slab_idx)))
        doc_freq = Counter()
        for k in range(len(P.slab_idx)):
            t = P.texts.get(ids[P.slab_idx[k]])
            if t is not None:
                doc_freq.update(set(K.words(t.title, t.text)))
        hovered_terms = ()
        if under:
            t = P.texts.get(ids[P.slab_idx[under[0]]])
            if t is not None:
                hovered_terms = tuple(TermWeight(term=w, weight=x, count=c) for w, x, c in
                                      K.tfidf(Counter(K.words(t.title, t.text)), doc_freq, len(P.slab_idx), req.top_terms))
        contrast = tuple(TermWeight(term=w, weight=x, count=c) for w, x, c in
                         K.contrast(_counts(P, under), slab_counts, req.top_terms)) if under else ()
        return LensReading(lens_radius=lr, records=records, hovered=records[0] if records else None,
                           hovered_terms=hovered_terms, contrast_terms=contrast)


class NumpyCandidateAdapter:
    def __init__(self, store):
        self.store = store

    def cluster(self, req: CandidateRequest) -> CandidateSet:
        P = _Pose(self.store, req.probe)
        c = req.probe.cloud
        ids = c.ids
        local = list(P.ap_local)
        if req.require_condensed and c.enrichment is not None:
            nuc = self.store.get(c.enrichment.nucleations)[ARMS.index(c.enrichment_arm)]
            local = [k for k in local if nuc[P.slab_idx[k]] > 0]
        pos = P.X[P.slab_idx[local]] if local else np.zeros((0, 3))
        comps, rest = K.mutual_knn_components(pos, req.k, req.min_size)
        ap_counts = _counts(P, local)
        all_d = np.linalg.norm(pos[:, None] - pos[None], axis=2) if len(pos) > 1 else np.zeros((1, 1))
        mean_all = float(all_d[np.triu_indices(len(pos), 1)].mean()) if len(pos) > 1 else 0.0
        clusters = []
        for g in comps[:req.max_clusters]:
            members = tuple(ids[P.slab_idx[local[x]]] for x in g)
            sub = all_d[np.ix_(g, g)]
            intra = float(sub[np.triu_indices(len(g), 1)].mean()) if len(g) > 1 else 0.0
            coh = max(0.0, min(1.0, 1 - intra / mean_all)) if mean_all > 0 else 0.0
            terms = tuple(w for w, _, _ in K.contrast(_counts(P, [local[x] for x in g]), ap_counts, req.top_terms))
            cen = P.uv[[local[x] for x in g]].mean(0)
            clusters.append(CandidateCluster(cluster_id=K.cluster_id(members), members=members,
                                             centroid=(float(cen[0]), float(cen[1])), cohesion=coh, suggested_terms=terms))
        pairs = ()
        if c.enrichment is not None:
            inside = {ids[P.slab_idx[k]] for k in P.ap_local}
            pairs = tuple(PairCandidate(a=s.a, b=s.b, source="enrichment_shortcut", score=s.score)
                          for s in c.enrichment.shortcuts if s.arm == c.enrichment_arm and s.a in inside and s.b in inside)
        return CandidateSet(request_digest=req.probe.digest(), clusters=tuple(clusters),
                            unclustered=tuple(ids[P.slab_idx[local[x]]] for x in rest), pairs=pairs)


def put_cloud(store, positions):
    """Explicit infrastructure conversion of the frozen 3D projection into the shared store."""
    return store.put(POSITIONS_SPEC, np.array(positions, dtype=np.float64, copy=True), producer="probe-input")
