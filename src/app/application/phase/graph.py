"""Forward-dependency checks over phase revisions (currentcraft-phase/v1). Pure Python; no arrays, no adapters.

Design source: docs/pipelines/PHASE_NUCLEATION.md ("Chain checks"). Only ``requires_accepted`` and ``nucleated_from``
are forward edges. A decision's ``entry_check_ref`` (the ``governs`` link) and intra-phase rework are not, so neither
can close a cycle here. These checks read records; they never accept, release or spawn a phase.
"""
from __future__ import annotations

from typing import Iterable, Optional

from app.application.phase.contracts import PhaseRevision


def _index(revisions: Iterable[PhaseRevision]) -> dict[str, PhaseRevision]:
    by_ref: dict[str, PhaseRevision] = {}
    for r in revisions:
        if r.ref in by_ref:
            raise ValueError(f"duplicate phase revision {r.ref}")
        by_ref[r.ref] = r
    return by_ref


def forward_edges(revisions: Iterable[PhaseRevision]) -> tuple[tuple[str, str], ...]:
    """Sorted ``(predecessor, successor)`` pairs from ``requires_accepted`` (``nucleated_from`` is always one of them).

    >>> a = PhaseRevision(phase_id="design", revision_id="r1", subsystem_id="a", ordinal=1, entry_profile_version="1")
    >>> b = PhaseRevision(phase_id="install", revision_id="r1", subsystem_id="a", ordinal=2, entry_profile_version="1",
    ...                   requires_accepted=("design@r1",), nucleated_from="design@r1")
    >>> forward_edges([b, a])
    (('design@r1', 'install@r1'),)
    """
    by_ref = _index(revisions)
    return tuple(sorted((p, ref) for ref, r in by_ref.items() for p in r.requires_accepted))


def missing_predecessors(revisions: Iterable[PhaseRevision]) -> tuple[tuple[str, str], ...]:
    """Sorted ``(successor, missing predecessor)`` pairs. A gap is reported, never filled in or guessed."""
    by_ref = _index(revisions)
    return tuple(sorted((ref, p) for ref, r in by_ref.items() for p in r.requires_accepted if p not in by_ref))


def find_forward_cycle(revisions: Iterable[PhaseRevision]) -> Optional[tuple[str, ...]]:
    """First forward-dependency cycle in sorted order, as ``(r0, r1, ..., r0)``; ``None`` if the forward graph is acyclic.

    Edges run predecessor -> successor. Missing predecessors are ignored here; report them with ``missing_predecessors``.
    """
    by_ref = _index(revisions)
    succ: dict[str, list[str]] = {ref: [] for ref in by_ref}
    for p, s in forward_edges(by_ref.values()):
        if p in succ:
            succ[p].append(s)
    state: dict[str, int] = {}  # 1 = on the current path, 2 = finished
    path: list[str] = []

    def visit(node: str) -> Optional[tuple[str, ...]]:
        state[node] = 1
        path.append(node)
        for nxt in succ[node]:
            if state.get(nxt) == 1:
                return tuple(path[path.index(nxt):]) + (nxt,)
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        path.pop()
        state[node] = 2
        return None

    for ref in sorted(succ):
        if ref not in state:
            found = visit(ref)
            if found:
                return found
    return None


def check_forward_dependencies(revisions: Iterable[PhaseRevision]) -> tuple[tuple[str, str], ...]:
    """Raise on duplicate revisions or a forward cycle; return missing predecessors as explicit gaps.

    >>> a = PhaseRevision(phase_id="design", revision_id="r1", subsystem_id="a", ordinal=1, entry_profile_version="1",
    ...                   requires_accepted=("install@r1",))
    >>> b = PhaseRevision(phase_id="install", revision_id="r1", subsystem_id="a", ordinal=2, entry_profile_version="1",
    ...                   requires_accepted=("design@r1",))
    >>> check_forward_dependencies([a, b])
    Traceback (most recent call last):
    ...
    ValueError: forward dependency cycle: design@r1 -> install@r1 -> design@r1
    """
    revisions = tuple(revisions)
    cycle = find_forward_cycle(revisions)
    if cycle:
        raise ValueError("forward dependency cycle: " + " -> ".join(cycle))
    return missing_predecessors(revisions)
