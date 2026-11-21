"""Internal source queries, not privacy-safe HTTP DTOs or approval claims.

Design: docs/architecture/HTTP_DOCUMENTS.md. Queries never commit. Revision
selection is pinned by identity, not a promise of database snapshot isolation.
"""
from typing import Literal

from app.application.ingest.contracts import DomainObject
from app.application.ingest.identity import subject_reference_id
from app.application.ingest.workbook_views import wbs_outline
from app.application.messaging.durable import inbox_key
from app.application.persistence.ports import UnitOfWorkFactory
from app.application.persistence.services import documents_for


def _current_revision(doc: DomainObject) -> str | None:
    current = {r.target_id for r in doc.relations if r.type == "current_revision"}
    if len(current) > 1:
        raise ValueError("document has multiple current revisions")
    return next(iter(current), None)


def document_head(uow_factory: UnitOfWorkFactory, document_id: str) -> DomainObject | None:
    with uow_factory() as uow:
        obj = uow.objects.get(document_id)
    return obj if obj is not None and obj.kind == "project_document" else None


def document_tasks(uow_factory: UnitOfWorkFactory, document_id: str,
                   all_revisions: bool = False) -> tuple[DomainObject, ...] | None:
    with uow_factory() as uow:
        doc = uow.objects.get(document_id)
        if doc is None or doc.kind != "project_document":
            return None
        if all_revisions:
            return uow.objects.related(document_id, rel_type="extracted_from",
                                       direction="in", kind="wbs_task")
        current = _current_revision(doc)
        if current is None:
            return ()
        tasks = uow.objects.related(document_id, rel_type="extracted_from",
                                     direction="in", kind="wbs_task")
        return tuple(t for t in tasks if any(
            r.type == "in_revision" and r.target_id == current for r in t.relations))


def document_outline(uow_factory: UnitOfWorkFactory, document_id: str) -> list[dict] | None:
    with uow_factory() as uow:
        doc = uow.objects.get(document_id)
        if doc is None or doc.kind != "project_document":
            return None
        current = _current_revision(doc)
        if current is None:
            return []
        objects = tuple(o for o in uow.objects.related(
            current, rel_type="in_revision", direction="in")
            if o.kind in ("phase_scope", "wbs_task"))
    return wbs_outline(objects)


def intake_status(uow_factory: UnitOfWorkFactory, handler_id: str,
                  event_id: str) -> Literal["pending", "processed", "quarantined"]:
    """Reflect the stored outcome, including legacy applied-marker limitations."""
    with uow_factory() as uow:
        record = uow.commands.get(inbox_key(handler_id, event_id))
    if record is None:
        return "pending"
    return "quarantined" if record.outcome == "rejected" else "processed"


def documents_for_reference(uow_factory: UnitOfWorkFactory, subject_kind: str,
                            namespace: str, reference: str) -> tuple[DomainObject, ...]:
    return documents_for(uow_factory, subject_reference_id(subject_kind, namespace, reference))
