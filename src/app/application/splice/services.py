"""Splice use cases: read phase evidence (pure Python), delegate hashing to the kernel port, persist embeddings."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional

from app.application.ingest.contracts import DomainObject
from app.application.persistence.ports import UnitOfWorkFactory

from .contracts import PhaseAssignment, PhaseEvidenceRule, SpliceProfile, SpliceRequest, SpliceResult
from .ports import SpliceKernelPort


def _code(v) -> Optional[str]:
    """Phase code from a scalar field. Integral floats become ints; blanks, bools and other floats are no evidence."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else None
    s = str(v).strip()
    return s or None


def _hours(v) -> Optional[float]:
    """Positive per-phase hours, or None. Blank never becomes zero, and zero is not phase evidence."""
    if v is None or isinstance(v, bool):
        return None
    try:
        h = float(v)
    except (TypeError, ValueError):
        return None
    return h if h > 0 and h == h and h != float("inf") else None


def _rule(profile: SpliceProfile, kind: str) -> Optional[PhaseEvidenceRule]:
    return next((r for r in profile.phase_rules if r.kind == kind), None)


def _field_code(profile: SpliceProfile, o: DomainObject) -> Optional[str]:
    r = _rule(profile, o.kind)
    return _code(o.fields.get(r.field)) if r is not None and r.source == "field" else None


def assign_phases(profile: SpliceProfile, objects: Iterable[DomainObject]) -> tuple[tuple[PhaseAssignment, ...], tuple[str, ...]]:
    """Phase evidence per object, in input order, plus diagnostics. Excluded kinds are skipped.

    Relation rules follow exactly one hop and only to targets whose own rule is a field rule (no chains, no guessing).
    A code the chart has no anchor for leaves the object unphased and is reported.
    """
    objects = tuple(objects)
    index = {o.object_id: o for o in objects}
    chart = profile.chart
    out, diags = [], []

    def finish(o, shares: Counter, basis: str):
        known = Counter({c: w for c, w in shares.items() if chart.angle_rad(c) is not None})
        for c in sorted(set(shares) - set(known)):
            diags.append(f"unanchored_phase_code: {o.object_id} carries phase '{c}' with no chart anchor")
        if not known:
            return PhaseAssignment(object_id=o.object_id, state="unphased",
                                   basis=basis + ("; code not anchored" if shares else ""))
        tot = sum(known.values())
        w = tuple((c, known[c] / tot) for c in sorted(known))
        if len(w) > 1:
            w = w[:-1] + ((w[-1][0], 1.0 - sum(x for _, x in w[:-1])),)
        return PhaseAssignment(object_id=o.object_id, state="phased" if len(w) == 1 else "mixed", weights=w, basis=basis)

    for o in objects:
        if o.kind in profile.excluded_kinds:
            continue
        r = _rule(profile, o.kind)
        if r is None:
            out.append(PhaseAssignment(object_id=o.object_id, state="unphased", basis="no phase rule for kind"))
        elif r.source == "field":
            c = _code(o.fields.get(r.field))
            out.append(finish(o, Counter({c: 1.0}) if c else Counter(), f"field {r.field}" + ("" if c else " absent")))
        elif r.source == "relation":
            shares = Counter()
            for rel in o.relations:
                t = index.get(rel.target_id)
                if rel.type in r.relation_types and t is not None:
                    c = _field_code(profile, t)
                    if c:
                        shares[c] += 1.0
            out.append(finish(o, shares, f"relation {'/'.join(r.relation_types)}" + ("" if shares else ": no phased target in batch")))
        else:
            shares = Counter()
            for a in chart.anchors:
                h = _hours(o.fields.get(r.hours_field_template.format(code=a.phase_code)))
                if h:
                    shares[a.phase_code] = h
            out.append(finish(o, shares, f"per-phase hours {r.hours_field_template}" + ("" if shares else ": none positive")))
    return tuple(out), tuple(diags)


class SpliceService:
    """Splice adapter output into a phase-blocked sparse space."""

    def __init__(self, kernel: SpliceKernelPort):
        self.kernel = kernel

    def splice(self, request: SpliceRequest) -> SpliceResult:
        assignments, diags = assign_phases(request.profile, request.objects)
        res = self.kernel.encode(request, assignments)
        return res.model_copy(update={"diagnostics": tuple(diags) + res.diagnostics})


def store_splice(uow_factory: UnitOfWorkFactory, result: SpliceResult) -> int:
    """Persist every sparse EmbeddingRecord in one transaction. Same object + space overwrites (one current vector)."""
    with uow_factory() as uow:
        for r in result.records:
            uow.embeddings.put(r.embedding)
        uow.commit()
    return len(result.records)
