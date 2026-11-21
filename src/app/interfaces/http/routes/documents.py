"""Token-protected, read-only routes over committed application queries.

Design: docs/architecture/HTTP_DOCUMENTS.md. Opaque resolution and all query
I/O execute in a worker thread; internal objects never reach a serializer.
"""
from __future__ import annotations

from typing import Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.application.ingest.contracts import DomainObject
from app.application.ingest.identity import subject_reference_id
from app.application.queries.documents import (
    document_head, document_outline, document_tasks, documents_for_reference,
)

from ..container import Container
from ..document_projection import (
    DocumentResponse, DocumentsResponse, TasksResponse, WbsResponse,
    outline_csv, project_document, project_outline, project_task,
)
from ..schemas import ErrorResponse
from ..security import require_token

LOOKUP_LIMIT = 10_000
ERRORS = {code: {"model": ErrorResponse} for code in (401, 404, 422, 500, 503)}
router = APIRouter(tags=["documents"], dependencies=[Depends(require_token)], responses=ERRORS)


def _container(request: Request, response: Response) -> Container:
    response.headers["Cache-Control"] = "no-store"
    container = request.app.state.container
    if container.uow_factory is None:
        raise HTTPException(status_code=503)
    return container


def _not_found() -> NoReturn:
    raise HTTPException(status_code=404)


def _resolve(container: Container, domain: Literal["doc", "sub"], handle: str,
             kind: str) -> DomainObject:
    """Fail closed rather than silently truncating the port's unpaged lookup."""
    if not container.handles.valid(domain, handle):
        _not_found()
    with container.uow_factory() as uow:
        candidates = uow.objects.by_kind(kind, limit=LOOKUP_LIMIT + 1)
    if len(candidates) > LOOKUP_LIMIT:
        raise HTTPException(status_code=503)
    matches = [obj for obj in candidates if obj.kind == kind and
               container.handles.matches(domain, obj.object_id, handle)]
    if len(matches) != 1:
        _not_found()
    return matches[0]


def _read_head(container: Container, handle: str) -> DocumentResponse:
    found = _resolve(container, "doc", handle, "project_document")
    head = document_head(container.uow_factory, found.object_id)
    if head is None:
        _not_found()
    return project_document(head, container.handles)


def _read_tasks(container: Container, handle: str, all_revisions: bool) -> TasksResponse:
    found = _resolve(container, "doc", handle, "project_document")
    tasks = document_tasks(container.uow_factory, found.object_id, all_revisions)
    if tasks is None:
        _not_found()
    return TasksResponse(document_id=handle, all_revisions=all_revisions,
                         tasks=tuple(project_task(task, container.handles) for task in tasks))


def _read_outline(container: Container, handle: str) -> WbsResponse:
    found = _resolve(container, "doc", handle, "project_document")
    rows = document_outline(container.uow_factory, found.object_id)
    if rows is None:
        _not_found()
    return WbsResponse(document_id=handle, rows=project_outline(rows, found.object_id, container.handles))


def _read_subject(container: Container, subject_kind: str, namespace: str,
                  reference: str) -> DocumentsResponse:
    if namespace != "opaque":
        raise HTTPException(status_code=422)
    subject = _resolve(container, "sub", reference, subject_kind + "_reference")
    # Private descriptors stay server-side. Reject corrupt stored binding data.
    raw_namespace, raw_reference = subject.fields.get("namespace"), subject.fields.get("reference")
    if not isinstance(raw_namespace, str) or not isinstance(raw_reference, str):
        raise RuntimeError("Invalid stored subject binding")
    try:
        expected_id = subject_reference_id(subject_kind, raw_namespace, raw_reference)
    except ValidationError:
        raise RuntimeError("Invalid stored subject binding") from None
    if expected_id != subject.object_id:
        raise RuntimeError("Invalid stored subject binding")
    docs = documents_for_reference(container.uow_factory, subject_kind, raw_namespace, raw_reference)
    return DocumentsResponse(documents=tuple(project_document(doc, container.handles) for doc in docs))


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str, container: Container = Depends(_container)) -> DocumentResponse:
    return await run_in_threadpool(_read_head, container, document_id)


@router.get("/documents/{document_id}/tasks", response_model=TasksResponse)
async def get_tasks(document_id: str, all_revisions: bool = False,
                    container: Container = Depends(_container)) -> TasksResponse:
    return await run_in_threadpool(_read_tasks, container, document_id, all_revisions)


@router.get("/documents/{document_id}/wbs", response_model=WbsResponse,
            responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}})
async def get_wbs(document_id: str, format: Literal["json", "csv"] = "json",
                  container: Container = Depends(_container)) -> WbsResponse | Response:
    safe = await run_in_threadpool(_read_outline, container, document_id)
    if format == "csv":
        return Response(outline_csv(safe.rows), media_type="text/csv",
                        headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="outline.csv"'})
    return safe


@router.get("/subjects/{subject_kind}/{namespace}/{reference}/documents", response_model=DocumentsResponse)
async def get_subject_documents(subject_kind: Literal["project", "opportunity"],
                                namespace: str, reference: str,
                                container: Container = Depends(_container)) -> DocumentsResponse:
    return await run_in_threadpool(_read_subject, container, subject_kind, namespace, reference)
