"""Privacy-safe read DTOs, never internal object serialization.

Design: docs/architecture/HTTP_DOCUMENTS.md. Framework-free and no repository
I/O. Every external value is constructed explicitly, not copied wholesale.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import re
import secrets
from typing import Annotated, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.application.ingest.contracts import DomainObject
from app.application.ingest.workbook_views import OUTLINE_COLUMNS

SOURCE_LABEL = "Source record (not approved work)"
Handle = Annotated[str, StringConstraints(pattern=r"^(doc|task|sub|wbs)_[0-9a-f]{64}$")]


class HandleCodec:
    """Process-local HMAC handles; key never derives from the bearer secret."""

    def __init__(self) -> None:
        self.__key = secrets.token_bytes(32)

    def encode(self, domain: Literal["doc", "task", "sub", "wbs"], value: str) -> str:
        if domain not in {"doc", "task", "sub", "wbs"}:
            raise ValueError("Invalid handle domain")
        digest = hmac.new(self.__key, (domain + "\0" + value).encode(), hashlib.sha256)
        return domain + "_" + digest.hexdigest()

    @staticmethod
    def valid(domain: str, value: str) -> bool:
        return re.fullmatch(re.escape(domain) + r"_[0-9a-f]{64}", value) is not None

    def matches(self, domain: Literal["doc", "task", "sub", "wbs"], value: str,
                handle: str) -> bool:
        return self.valid(domain, handle) and hmac.compare_digest(self.encode(domain, value), handle)


class _DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SubjectLink(_DTO):
    subject_kind: Literal["project", "opportunity"] = Field(description="Allowlisted subject category, not authority.")
    namespace: Literal["opaque"] = Field(default="opaque", description="Public namespace marker, never the source namespace.")
    reference: Handle = Field(description="Process-local opaque subject handle.")


class DocumentResponse(_DTO):
    object_id: Handle = Field(description="Process-local opaque document handle, not its persisted identity.")
    kind: Literal["project_document"] = Field(default="project_document", description="Fixed source-object category.")
    assertion: Literal["source_record"] = Field(default="source_record", description="Committed source record, not approval evidence.")
    approved_work: Literal[False] = Field(default=False, description="This projection never grants work approval.")
    subjects: tuple[SubjectLink, ...] = Field(default=(), description="Opaque subject links only, without relation evidence.")


class TaskResponse(_DTO):
    object_id: Handle = Field(description="Process-local opaque occurrence handle.")
    kind: Literal["wbs_task"] = Field(default="wbs_task", description="Fixed source-occurrence category.")
    assertion: Literal["source_record"] = Field(default="source_record", description="Extracted occurrence, not an approved task.")
    approved_work: Literal[False] = Field(default=False, description="Source occurrences are never executable-work approval.")


class TasksResponse(_DTO):
    document_id: Handle = Field(description="Opaque handle of the selected source document.")
    all_revisions: bool = Field(description="Whether all retained revisions were explicitly requested.")
    tasks: tuple[TaskResponse, ...] = Field(description="Allowlisted source occurrences only.")
    assertion: Literal["source_records_not_approved_work"] = Field(default="source_records_not_approved_work", description="No task or work approval is asserted.")


class WbsRow(_DTO):
    wbs_code: str | None = Field(default=None, description="Document-scoped opaque structural code, when present.")
    parent_wbs_code: str | None = Field(default=None, description="Opaque parent structural code, when present.")
    wbs_level: int | None = Field(default=None, ge=0, le=64, description="Bounded structural level only.")
    name: Literal["Source record (not approved work)"] = Field(default=SOURCE_LABEL, description="Fixed replacement for the private source title.")
    row_kind: Literal["phase", "task", "source_record"] = Field(description="Allowlisted structural row category.")
    phase_code: None = Field(default=None, description="Withheld private source cell.")
    subsystem_code: None = Field(default=None, description="Withheld private source cell.")
    subsystem_state: None = Field(default=None, description="Withheld private source cell.")
    hierarchy_basis: None = Field(default=None, description="Withheld private source cell.")
    parent_status: None = Field(default=None, description="Withheld private source cell.")
    labor_hours_known: None = Field(default=None, description="Withheld private source cell.")
    roles_with_input: None = Field(default=None, description="Withheld private source cell.")
    labor_sources: None = Field(default=None, description="Withheld private source cell.")
    responsible_party: None = Field(default=None, description="Withheld private source cell.")
    responsibility_raw: None = Field(default=None, description="Withheld private source cell.")
    locator: None = Field(default=None, description="Withheld private source locator.")


class WbsResponse(_DTO):
    document_id: Handle = Field(description="Opaque source-document handle.")
    columns: tuple[str, ...] = Field(default=OUTLINE_COLUMNS, description="Exact internal outline column order, not permission to disclose cells.")
    rows: tuple[WbsRow, ...] = Field(description="Privacy-projected structural outline.")
    assertion: Literal["source_records_not_approved_work"] = Field(default="source_records_not_approved_work", description="An outline never grants work approval.")


class DocumentsResponse(_DTO):
    documents: tuple[DocumentResponse, ...] = Field(description="Allowlisted documents bound to the opaque subject.")


def project_document(obj: DomainObject, codec: HandleCodec) -> DocumentResponse:
    if obj.kind != "project_document":
        raise ValueError("Unexpected source-object category")
    subjects = set()
    for relation in obj.relations:
        if relation.type != "document_of":
            continue
        for kind in ("project", "opportunity"):
            if relation.target_id.startswith("ref:" + kind + ":"):
                subjects.add((kind, codec.encode("sub", relation.target_id)))
    return DocumentResponse(object_id=codec.encode("doc", obj.object_id), subjects=tuple(
        SubjectLink(subject_kind=kind, reference=handle) for kind, handle in sorted(subjects)))


def project_task(obj: DomainObject, codec: HandleCodec) -> TaskResponse:
    if obj.kind != "wbs_task":
        raise ValueError("Unexpected source-object category")
    return TaskResponse(object_id=codec.encode("task", obj.object_id))


def _code(codec: HandleCodec, document_id: str, value: object) -> str | None:
    if type(value) is str and value:
        return codec.encode("wbs", document_id + "\0" + value)
    return None


def project_outline(rows: Iterable[dict], document_id: str, codec: HandleCodec) -> tuple[WbsRow, ...]:
    result = []
    for row in rows:
        level = row.get("wbs_level")
        kind = row.get("row_kind")
        result.append(WbsRow(
            wbs_code=_code(codec, document_id, row.get("wbs_code")),
            parent_wbs_code=_code(codec, document_id, row.get("parent_wbs_code")),
            wbs_level=level if type(level) is int and 0 <= level <= 64 else None,
            row_kind=kind if kind in ("phase", "task") else "source_record",
        ))
    return tuple(result)


def escape_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def outline_csv(rows: Iterable[WbsRow]) -> str:
    """Only typed, already-projected rows may reach CSV rendering."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(OUTLINE_COLUMNS)
    for row in rows:
        if not isinstance(row, WbsRow):
            raise TypeError("Expected a projected outline row")
        values = row.model_dump()
        writer.writerow(escape_csv_cell(values[column]) for column in OUTLINE_COLUMNS)
    return output.getvalue()
