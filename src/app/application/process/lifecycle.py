"""Object lifecycle derivation: births and deaths happen only at processes (docs/domain/PROCESS_FIRST.md)."""

from __future__ import annotations

from typing import Iterable

from .contracts import ObjectEvent, ProcessExecution


class LifecycleError(ValueError):
    """An execution sequence violates object lifecycle rules."""


def derive_object_events(executions: Iterable[ProcessExecution], preexisting: Iterable[str] = ()) -> tuple[ObjectEvent, ...]:
    """Replay executions in the given order. Release, return and transfer are state changes, not deaths.

    >>> from app.application.process.contracts import ObjectIncidence, ProcessType
    >>> t = ProcessType(code="t", name="Transform", function_classes=("transform",))
    >>> kill = ProcessExecution(execution_id="x:1", process=t, stage="S",
    ...                         incidence=(ObjectIncidence(object_id="o", effect="consumes"),))
    >>> derive_object_events((kill,))
    Traceback (most recent call last):
    ...
    app.application.process.lifecycle.LifecycleError: x:1: consumes 'o' which is not alive
    """
    alive: dict[str, str | None] = {o: None for o in preexisting}
    dead: set[str] = set()
    out: list[ObjectEvent] = []

    def emit(ex, oid, kind, state):
        out.append(ObjectEvent(object_id=oid, kind=kind, state=state, execution_id=ex.execution_id, stage=ex.stage,
                               occurred_at=ex.occurred_at, index=len(out)))

    for ex in executions:
        for inc in ex.incidence:
            oid = inc.object_id
            if inc.effect == "produces":
                if oid in alive:
                    raise LifecycleError(f"{ex.execution_id}: produces {oid!r} which is already alive")
                if oid in dead:
                    raise LifecycleError(f"{ex.execution_id}: produces {oid!r} after its death; use a new object id")
                alive[oid] = inc.state_after
                emit(ex, oid, "birth", inc.state_after)
                continue
            if oid not in alive:
                where = "after its death" if oid in dead else "which is not alive"
                raise LifecycleError(f"{ex.execution_id}: {inc.effect} {oid!r} {where}")
            if inc.state_before is not None and alive[oid] is not None and alive[oid] != inc.state_before:
                raise LifecycleError(f"{ex.execution_id}: {oid!r} is {alive[oid]!r}, expected {inc.state_before!r}")
            if inc.effect == "consumes":
                del alive[oid]
                dead.add(oid)
                emit(ex, oid, "death", None)
            elif inc.state_after is not None:
                alive[oid] = inc.state_after
                emit(ex, oid, "state_change", inc.state_after)
    return tuple(out)


def alive_at_end(events: Iterable[ObjectEvent], preexisting: Iterable[str] = ()) -> tuple[str, ...]:
    """Objects whose lifetime is censored (never consumed) at the end of the window."""
    alive = set(preexisting)
    for e in events:
        if e.kind == "birth":
            alive.add(e.object_id)
        elif e.kind == "death":
            alive.discard(e.object_id)
    return tuple(sorted(alive))
