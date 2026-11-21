"""Authenticated, bounded document intake. No extraction or infrastructure imports."""

import hashlib
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from python_multipart.multipart import parse_options_header
from python_multipart.exceptions import MultipartParseError

from app.application.ingest.contracts import BlobRef, IntakeBinding, RawItem
from app.application.ingest.services import raw_item_event
from app.application.messaging.durable import PublishReceipt
from app.application.queries.documents import intake_status
from ..security import require_token

FILE_LIMIT = 64 * 1024 * 1024
REQUEST_LIMIT = FILE_LIMIT + 64 * 1024
OVERHEAD_LIMIT = 64 * 1024
CORE_BINDING = ("subject_kind", "subject_namespace", "subject_ref", "document_type")
FIELDS = ("format", "source_id", "mapping", *CORE_BINDING, "revision_label")
MEDIA = {"text": "text/plain", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

router = APIRouter(tags=["intake"], dependencies=[Depends(require_token)])


class IntakeReceipt(BaseModel):
    event_id: str = Field(description="Opaque receipt handle, not the internal event ID.")
    stream: Literal["DM_RAW"] = Field(description="Stream confirming durable acceptance.")
    sequence: int = Field(ge=1, description="Broker sequence, not a business version.")
    duplicate: bool = Field(description="Broker-window duplicate flag; not exactly-once.")
    source_id: str = Field(description="Opaque source receipt handle, never the supplied source ID.")
    content_sha256: str = Field(description="Digest of the submitted file bytes.")
    status_url: str = Field(description="Authenticated relative status URL with an opaque handle.")
    detail: str = Field(description="Queued does not mean extracted or approved.")


class IntakeStatus(BaseModel):
    event_id: str = Field(description="Opaque receipt handle.")
    status: Literal["pending", "processed", "quarantined"] = Field(description="Stored inbox outcome.")
    detail: str = Field(description="Status limitations; never work approval.")


class BoundedParser(MultiPartParser):
    # Starlette renamed max_file_size to spool_max_size; bound both versions.
    spool_max_size = 1024 * 1024
    max_file_size = 1024 * 1024
    max_part_size = 4096

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_file_bytes = 0
        self.header_bytes = 0
        self.complete = False

    def on_part_begin(self) -> None:
        self.file_bytes = 0
        super().on_part_begin()

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._current_part.file is not None:
            self.file_bytes += end - start
            self.total_file_bytes += end - start
            if self.file_bytes > FILE_LIMIT:
                raise MultiPartException("Request size exceeded.")
        elif len(self._current_part.data) + end - start > 4096:
            raise MultiPartException("Invalid field size.")
        super().on_part_data(data, start, end)

    def _header_size(self, size: int) -> None:
        self.header_bytes += size
        if self.header_bytes > 16 * 1024:
            raise MultiPartException("Request size exceeded.")

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_size(end - start)
        super().on_header_field(data, start, end)

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_size(end - start)
        super().on_header_value(data, start, end)

    def on_end(self) -> None:
        self.complete = True
        super().on_end()


async def _form(request: Request):
    content_type = request.headers.get("content-type", "")
    if len(content_type) > 4096:
        raise HTTPException(413)
    media, options = parse_options_header(content_type)
    boundary = options.get(b"boundary", b"")
    if (media != b"multipart/form-data" or not 1 <= len(boundary) <= 200
            or options.get(b"charset", b"utf-8").lower() != b"utf-8"):
        raise HTTPException(422)

    async def bounded_stream():
        total = 0
        async for chunk in request.stream():
            # Keep parser buffers bounded even if ASGI supplies one huge chunk.
            for start in range(0, len(chunk), 16 * 1024):
                piece = chunk[start:start + 16 * 1024]
                total += len(piece)
                if total > REQUEST_LIMIT:
                    raise MultiPartException("Request size exceeded.")
                yield piece
                if total - parser.total_file_bytes > OVERHEAD_LIMIT:
                    raise MultiPartException("Request size exceeded.")
    parser = BoundedParser(request.headers, bounded_stream(), max_files=1, max_fields=8)
    try:
        result = await parser.parse()
        if not parser.complete:
            raise MultiPartException("Incomplete multipart.")
        return result
    except MultiPartException as exc:
        for handle in parser._files_to_close_on_error:
            handle.close()
        # Starlette 1.10 wraps native parser errors; inspect the typed cause
        # for fixed limit categories without returning/logging its message.
        cause = exc.__cause__
        native_limit = isinstance(cause, MultipartParseError) and cause.args in (
            ("Maximum header size exceeded",),
            ("Maximum header count exceeded",),
        )
        if exc.message == "Request size exceeded." or native_limit:
            raise HTTPException(413) from None
        raise HTTPException(422) from None
    except MultipartParseError as exc:
        # Newer python-multipart enforces its own limits before callbacks run.
        # Classify only its fixed limit categories, never echo parser text.
        for handle in parser._files_to_close_on_error:
            handle.close()
        limited = exc.args in (
            ("Maximum header size exceeded",),
            ("Maximum header count exceeded",),
        )
        raise HTTPException(413 if limited else 422) from None
    except BaseException:
        # Also close files on malformed parser input, cancellation and disconnect.
        for handle in parser._files_to_close_on_error:
            handle.close()
        raise


_BODY = {"requestBody": {"required": True, "content": {"multipart/form-data": {
    "schema": {"type": "object", "required": ["file", "format", "source_id"], "properties": {
        "file": {"type": "string", "format": "binary"},
        **{name: ({"type": "string", "enum": ["xlsx", "text"]} if name == "format" else {"type": "string"})
           for name in FIELDS},
    }},
}}}}


@router.post("/intake/documents", status_code=202, response_model=IntakeReceipt,
             responses={401: {"description": "Unauthorized"}, 413: {"description": "Upload too large"},
                        422: {"description": "Invalid intake"}, 503: {"description": "Storage or publish unavailable"}},
             openapi_extra=_BODY)
async def intake_document(request: Request) -> IntakeReceipt:
    form = None
    try:
        container = request.app.state.container
        if container.blobs is None or container.receipts is None or container.intake_broker is None:
            raise HTTPException(503)
        form = await _form(request)
        pairs = list(form.multi_items())
        if len({k for k, _ in pairs}) != len(pairs) or any(k not in (*FIELDS, "file") for k, _ in pairs):
            raise HTTPException(422)
        file = form.get("file")
        values = {k: v for k, v in pairs if k != "file"}
        if not isinstance(file, UploadFile) or any(not isinstance(v, str) or len(v.encode()) > 4096 for v in values.values()):
            raise HTTPException(422)
        fmt, source = values.get("format"), values.get("source_id")
        if fmt not in MEDIA or source is None:
            raise HTTPException(422)
        binding = None
        if any(k in values for k in (*CORE_BINDING, "revision_label")):
            if not all(k in values for k in CORE_BINDING):
                raise HTTPException(422)
            binding = IntakeBinding(**{k: values[k] for k in (*CORE_BINDING, "revision_label") if k in values})
        data = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            if len(data) + len(chunk) > FILE_LIMIT:
                raise HTTPException(413)
            data.extend(chunk)
        digest = hashlib.sha256(data).hexdigest()
        expected = BlobRef(key="sha256:" + digest, sha256=digest, size=len(data), media_type=MEDIA[fmt])
        raw = RawItem(platform="file", format=fmt, source_id=source,
                      received_at=datetime.now(timezone.utc), content=expected,
                      mapping=values.get("mapping"), binding=binding)
        # Validate the event too, before external writes. CLI construction is unchanged.
        raw_item_event(raw)
        try:
            stored_blob = await run_in_threadpool(container.blobs.put, bytes(data), MEDIA[fmt])
            if stored_blob != expected:
                raise RuntimeError("Invalid blob confirmation.")
            first = await run_in_threadpool(container.receipts.select_first, raw)
            event = raw_item_event(first.raw)
            confirmation = PublishReceipt.model_validate(
                (await container.intake_broker.publish(event)).model_dump())
            if confirmation.stream != "DM_RAW":
                raise RuntimeError("Invalid stream confirmation.")
            return IntakeReceipt(event_id=first.event_handle, stream="DM_RAW", sequence=confirmation.sequence,
                                 duplicate=confirmation.duplicate, source_id=first.source_handle,
                                 content_sha256=digest, status_url="/v1/intake/" + first.event_handle,
                                 detail="Durably queued; not extracted. No work approval is implied.")
        except Exception:
            raise HTTPException(503) from None
    except HTTPException:
        raise
    except ValidationError:
        raise HTTPException(422) from None
    except Exception:
        raise HTTPException(422 if form is None else 503) from None
    finally:
        if form is not None:
            try:
                await form.close()
            except Exception:
                raise HTTPException(503) from None


@router.get("/intake/{event_id}", response_model=IntakeStatus,
            responses={401: {"description": "Unauthorized"}, 422: {"description": "Invalid handle"},
                       503: {"description": "Status unavailable"}})
async def get_intake_status(request: Request, event_id: str = Path(pattern=r"^intake_[0-9a-f]{32}$")) -> IntakeStatus:
    try:
        container = request.app.state.container
        if container.receipts is None or container.uow_factory is None:
            raise HTTPException(503)
        first = await run_in_threadpool(container.receipts.get, event_id)
        status = "pending" if first is None else await run_in_threadpool(
            intake_status, container.uow_factory, container.settings.intake_handler_id,
            raw_item_event(first.raw).event_id)
        return IntakeStatus(event_id=event_id, status=status,
                            detail="Pending does not prove queue membership. Processed means committed source occurrences, not approved work.")
    except Exception:
        raise HTTPException(503) from None
