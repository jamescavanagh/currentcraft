"""Event-chain sequence checks and deterministic replay for phase transitions (currentcraft-phase/v1). Pure Python.

Design source: docs/pipelines/PHASE_NUCLEATION.md ("Event chains"). A chain is every event for one phase revision on one
trace; simulation and governance chains never mix. Retries are classified with ``PhaseTransitionEvent.replay_against``
before any sequence check. Replay fails closed: it returns states and digests only when no chain issue exists.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import timezone
from typing import Iterable

from app.application.phase.contracts import SCHEMA_VERSION, PhaseTransitionEvent

CHAIN_ISSUES: tuple[str, ...] = ("key_conflict", "event_id_conflict", "missing_creation", "sequence_gap", "sequence_fork",
                                 "state_mismatch", "time_regression")


def chain_key(e: PhaseTransitionEvent) -> str:
    return f"{e.phase_ref}/{e.trace}"


def _canonical_order(e: PhaseTransitionEvent):
    return (e.occurred_at.astimezone(timezone.utc), e.event_id, e.idempotency_key, e.sequence)


def dedupe(events: Iterable[PhaseTransitionEvent]):
    """Drop no-op retries; return ``(kept events, issues)``. The canonically first event under a key is the stored one."""
    by_key: dict[str, PhaseTransitionEvent] = {}
    by_id: dict[str, PhaseTransitionEvent] = {}
    kept, issues = [], []
    for e in sorted(events, key=_canonical_order):
        verdict = e.replay_against(by_key.get(e.idempotency_key))
        if verdict == "noop":
            continue
        if verdict == "conflict":
            issues.append((chain_key(e), e.event_id, "key_conflict"))
            continue
        if e.event_id in by_id:
            issues.append((chain_key(e), e.event_id, "event_id_conflict"))
            continue
        by_key[e.idempotency_key] = by_id[e.event_id] = e
        kept.append(e)
    return tuple(kept), tuple(issues)


def _chains(events: Iterable[PhaseTransitionEvent]) -> dict[str, dict[int, list[PhaseTransitionEvent]]]:
    chains: dict[str, dict[int, list[PhaseTransitionEvent]]] = defaultdict(lambda: defaultdict(list))
    for e in events:
        chains[chain_key(e)][e.sequence].append(e)
    return chains


def chain_issues(events: Iterable[PhaseTransitionEvent]) -> tuple[tuple[str, str, str], ...]:
    """Sorted ``(chain, event_id, issue)`` for every retry conflict and sequence problem. See ``CHAIN_ISSUES``."""
    kept, issues = dedupe(events)
    issues = list(issues)
    for key, by_seq in _chains(kept).items():
        for es in by_seq.values():
            if len(es) > 1:
                issues.extend((key, e.event_id, "sequence_fork") for e in es)
        seqs = sorted(by_seq)
        if seqs[0] != 0:
            issues.append((key, by_seq[seqs[0]][0].event_id, "missing_creation"))
        for s in seqs[1:]:
            if s - 1 not in by_seq:
                issues.extend((key, e.event_id, "sequence_gap") for e in by_seq[s])
                continue
            if len(by_seq[s]) > 1 or len(by_seq[s - 1]) > 1:
                continue  # a fork is already reported; no single predecessor to compare
            prev, e = by_seq[s - 1][0], by_seq[s][0]
            if e.prior_state != prev.next_state:
                issues.append((key, e.event_id, "state_mismatch"))
            if e.occurred_at < prev.occurred_at:
                issues.append((key, e.event_id, "time_regression"))
    return tuple(sorted(issues))


def chain_digest(chain: Iterable[PhaseTransitionEvent]) -> str:
    """SHA-256 over the canonical, sequence-ordered content of one chain; independent of input order and retries."""
    rows = [[e.sequence, e.event_id, e.idempotency_key, e.phase_ref, e.trace, e.prior_state, e.next_state, e.input_digest,
             e.transition_policy_version, e.decision_ref, list(e.evidence_refs),
             e.occurred_at.astimezone(timezone.utc).isoformat()] for e in sorted(chain, key=lambda e: e.sequence)]
    payload = json.dumps({"schema": SCHEMA_VERSION, "events": rows}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def replay_chains(events: Iterable[PhaseTransitionEvent]) -> tuple[tuple[str, str, str, int, str], ...]:
    """Sorted ``(phase_ref, trace, final_state, length, digest)`` per chain; raises ``ValueError`` on any chain issue.

    >>> from datetime import datetime, timezone
    >>> e0 = PhaseTransitionEvent(event_id="e0", idempotency_key="k0", phase_ref="design@r1", sequence=0, prior_state=None,
    ...     next_state="possible", input_digest="0" * 64, transition_policy_version="1", trace="simulation",
    ...     occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    >>> [row[:4] for row in replay_chains([e0, e0])]
    [('design@r1', 'simulation', 'possible', 1)]
    """
    events = tuple(events)
    issues = chain_issues(events)
    if issues:
        raise ValueError(f"event chain issues: {issues}")
    kept, _ = dedupe(events)
    out = []
    for key, by_seq in _chains(kept).items():
        chain = [es[0] for _, es in sorted(by_seq.items())]
        out.append((chain[-1].phase_ref, chain[-1].trace, chain[-1].next_state, len(chain), chain_digest(chain)))
    return tuple(sorted(out))
