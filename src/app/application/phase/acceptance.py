"""Predecessor-acceptance checks over phase revisions and decisions (currentcraft-phase/v1). Pure Python.

Design source: docs/pipelines/PHASE_NUCLEATION.md ("Predecessor acceptance"). A predecessor counts as accepted for a
successor only through a human ``AcceptanceDecision`` on that exact revision, evaluated against that successor's
published entry check, decided at or before the reading time and not expired. Simulated transitions, labels and scores
never count. These functions read records; eligibility to leave ``possible`` is a structural reading, not a release.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.application.phase.contracts import AcceptanceDecision, PhaseRevision, PhaseTransitionEvent

PREDECESSOR_STATUSES: tuple[str, ...] = ("accepted", "held", "returned", "undecided", "expired", "conflict",
                                         "other_entry_check", "missing")


def _aware(at: datetime) -> datetime:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return at


def _index(revisions: Iterable[PhaseRevision]) -> dict[str, PhaseRevision]:
    by_ref: dict[str, PhaseRevision] = {}
    for r in revisions:
        if r.ref in by_ref:
            raise ValueError(f"duplicate phase revision {r.ref}")
        by_ref[r.ref] = r
    return by_ref


def pair_status(successor: PhaseRevision, predecessor_ref: str, decisions: Iterable[AcceptanceDecision],
                as_of: datetime, known: bool = True) -> str:
    """Status of one predecessor for one successor at ``as_of``. See ``PREDECESSOR_STATUSES``."""
    as_of = _aware(as_of)
    if not known:
        return "missing"
    seen = [d for d in decisions if d.phase_ref == predecessor_ref and d.decided_at <= as_of]
    relevant = sorted((d for d in seen if d.entry_check_ref == successor.entry_profile_version), key=lambda d: d.decided_at)
    if not relevant:
        return "other_entry_check" if any(d.outcome == "accept" for d in seen) else "undecided"
    latest_at = relevant[-1].decided_at
    if len({d.outcome for d in relevant if d.decided_at == latest_at}) > 1:
        return "conflict"
    first_accept = next((i for i, d in enumerate(relevant) if d.outcome == "accept"), None)
    if first_accept is not None and any(d.outcome != "accept" for d in relevant[first_accept:]):
        return "conflict"  # accepted is absorbing for a fixed revision; a later issue needs a new revision
    latest = relevant[-1]
    if latest.outcome == "accept":
        return "expired" if latest.expires_at is not None and latest.expires_at <= as_of else "accepted"
    return "held" if latest.outcome == "hold" else "returned"


def predecessor_statuses(revisions: Iterable[PhaseRevision], decisions: Iterable[AcceptanceDecision],
                         as_of: datetime) -> tuple[tuple[str, str, str], ...]:
    """Sorted ``(successor, predecessor, status)`` for every required predecessor at ``as_of``.

    >>> from datetime import datetime, timezone
    >>> a = PhaseRevision(phase_id="design", revision_id="r1", subsystem_id="a", ordinal=1, entry_profile_version="d/1")
    >>> b = PhaseRevision(phase_id="install", revision_id="r1", subsystem_id="a", ordinal=2, entry_profile_version="i/1",
    ...                   requires_accepted=("design@r1",), nucleated_from="design@r1")
    >>> predecessor_statuses([a, b], [], datetime(2026, 1, 1, tzinfo=timezone.utc))
    (('install@r1', 'design@r1', 'undecided'),)
    """
    as_of = _aware(as_of)
    by_ref, decisions = _index(revisions), tuple(decisions)
    return tuple(sorted((ref, p, pair_status(r, p, decisions, as_of, p in by_ref))
                        for ref, r in by_ref.items() for p in r.requires_accepted))


def eligible_to_leave_possible(revisions: Iterable[PhaseRevision], decisions: Iterable[AcceptanceDecision],
                               as_of: datetime) -> tuple[str, ...]:
    """Sorted revisions whose required predecessors are all ``accepted`` at ``as_of``. Eligibility is not a release."""
    revisions = tuple(revisions)
    blocked = {s for s, _, status in predecessor_statuses(revisions, decisions, as_of) if status != "accepted"}
    return tuple(sorted(r.ref for r in revisions if r.ref not in blocked))


def governance_violations(revisions: Iterable[PhaseRevision], decisions: Iterable[AcceptanceDecision],
                          events: Iterable[PhaseTransitionEvent]) -> tuple[tuple[str, str, str], ...]:
    """Sorted ``(event_id, predecessor or phase, status)`` for governance events that leave ``possible`` too early.

    Each event is read at its own ``occurred_at``, so a later decision can never backdate it. Simulation events are
    ignored: they carry no authority. An event for a revision outside the set is reported as ``unknown_revision``.
    """
    by_ref, decisions = _index(revisions), tuple(decisions)
    out = []
    for e in events:
        if e.trace != "governance" or e.prior_state != "possible":
            continue
        succ = by_ref.get(e.phase_ref)
        if succ is None:
            out.append((e.event_id, e.phase_ref, "unknown_revision"))
            continue
        for p in succ.requires_accepted:
            status = pair_status(succ, p, decisions, e.occurred_at, p in by_ref)
            if status != "accepted":
                out.append((e.event_id, p, status))
    return tuple(sorted(out))
