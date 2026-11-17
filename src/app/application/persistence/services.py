"""Persistence use cases: store ingest output with its events, run idempotent commands, relay the outbox."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable, Optional, Type, TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.application.ingest.contracts import DomainObject
from app.application.messaging.contracts import make_event
from app.application.messaging.ports import MessageBrokerPort

from .contracts import CommandRecord, Reservation, StoreResult, VersionedRecord
from .ports import UnitOfWorkFactory

M = TypeVar("M", bound=BaseModel)


def persist_objects(uow_factory: UnitOfWorkFactory, objects: Iterable[DomainObject], at: datetime) -> tuple[StoreResult, ...]:
    """Store source occurrences, their edges and one domain.stored event per new version, in one transaction."""
    results = []
    with uow_factory() as uow:
        for obj in objects:
            res = uow.objects.put(obj)
            results.append(res)
            if res.stored:
                uow.outbox.add(make_event(topic=f"stored/{obj.kind}/{obj.object_id}", kind="domain.stored", source="persistence",
                                          epistemic_status="computed", occurred_at=at,
                                          payload={"object_id": obj.object_id, "kind": obj.kind, "version_no": res.version_no,
                                                   "digest": obj.digest()}), at)
        uow.commit()
    return tuple(results)


def save_aggregate(uow_factory: UnitOfWorkFactory, aggregate_type: str, aggregate_id: UUID, model: BaseModel,
                   expected_version: Optional[int], at: datetime, command_id: Optional[str] = None,
                   schema_version: str = "v1") -> VersionedRecord:
    """Compare-and-swap save of a Pydantic aggregate. Payload is model_dump(mode='json'): Decimals stay exact strings."""
    with uow_factory() as uow:
        rec = uow.aggregates.save(VersionedRecord(aggregate_type=aggregate_type, aggregate_id=aggregate_id,
                                                  version=(expected_version or 0) + 1, schema_version=schema_version,
                                                  payload=model.model_dump(mode="json"), recorded_at=at, command_id=command_id),
                                  expected_version)
        uow.commit()
    return rec


def load_aggregate(uow_factory: UnitOfWorkFactory, aggregate_type: str, aggregate_id: UUID, model: Type[M]) -> Optional[tuple[M, int]]:
    with uow_factory() as uow:
        rec = uow.aggregates.get(aggregate_type, aggregate_id)
    return (model.model_validate(rec.payload), rec.version) if rec else None


def run_once(uow_factory: UnitOfWorkFactory, command_id: str, command_type: str, at: datetime,
             action: Callable[[object], Optional[str]]) -> CommandRecord:
    """Apply a command at most once. A replayed command id returns the first outcome and does nothing."""
    with uow_factory() as uow:
        prior = uow.commands.get(command_id)
        if prior is not None:
            return prior
        result_ref = action(uow)
        rec = CommandRecord(command_id=command_id, command_type=command_type, outcome="applied", result_ref=result_ref, recorded_at=at)
        uow.commands.record(rec)
        uow.commit()
    return rec


def reserve_stock(uow_factory: UnitOfWorkFactory, reservation: Reservation) -> Reservation:
    """Reserve shared stock once per command id; overcommit raises InsufficientStock and reserves nothing."""
    with uow_factory() as uow:
        r = uow.stock.reserve(reservation)
        uow.commit()
    return r


def relay_outbox(uow_factory: UnitOfWorkFactory, broker: MessageBrokerPort, at: datetime, limit: int = 500) -> int:
    """Publish committed events, then mark them. At-least-once: the broker drops duplicate event ids."""
    from app.application.messaging.contracts import EventEnvelope
    with uow_factory() as uow:
        pending = uow.outbox.pending(limit)
    sent = []
    for e in pending:
        broker.publish(EventEnvelope.model_validate(e.envelope))
        sent.append(e.event_id)
    if sent:
        with uow_factory() as uow:
            uow.outbox.mark_published(tuple(sent), at)
            uow.commit()
    return len(sent)


def documents_for(uow_factory: UnitOfWorkFactory, subject_id: str) -> tuple[DomainObject, ...]:
    """Project documents (e.g. estimation workbooks) tied to a project or opportunity reference."""
    with uow_factory() as uow:
        return uow.objects.related(subject_id, rel_type="document_of", direction="in", kind="project_document")


def tasks_of(uow_factory: UnitOfWorkFactory, document_id: str, all_revisions: bool = False) -> tuple[DomainObject, ...]:
    """Task occurrences extracted from a project document; by default only from its current revision."""
    with uow_factory() as uow:
        tasks = uow.objects.related(document_id, rel_type="extracted_from", direction="in", kind="wbs_task")
        doc = uow.objects.get(document_id)
    if all_revisions or doc is None:
        return tasks
    current = {r.target_id for r in doc.relations if r.type == "current_revision"}
    return tuple(t for t in tasks if any(r.type == "in_revision" and r.target_id in current for r in t.relations))
