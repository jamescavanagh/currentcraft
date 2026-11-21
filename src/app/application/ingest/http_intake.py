"""HTTP intake contracts/ports, independent of frameworks and drivers."""

from typing import Protocol

from pydantic import Field

from app.application.common.contracts import _Frozen
from app.application.ingest.contracts import BlobRef, RawItem


class StoredIntake(_Frozen):
    raw: RawItem = Field(description="First validated intake, private server-side.")
    event_handle: str = Field(pattern=r"^intake_[0-9a-f]{32}$", description="Opaque HTTP handle.")
    source_handle: str = Field(pattern=r"^source_[0-9a-f]{32}$", description="Opaque source receipt handle.")


class IntakeBlobStore(Protocol):
    def put(self, data: bytes, media_type: str) -> BlobRef: ...


class IntakeReceiptStore(Protocol):
    def select_first(self, raw: RawItem) -> StoredIntake: ...
    def get(self, event_handle: str) -> StoredIntake | None: ...
