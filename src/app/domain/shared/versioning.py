"""P4 references and proposal base; no storage, clocks or operating grant."""
from datetime import datetime
from typing import Annotated, ClassVar, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from app.domain.versioning import VersionedEntity

Code = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
Label = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]


class VersionRef(BaseModel):
    """Exact immutable reference, retaining the PR #4 serialized shape."""
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    identity: UUID
    version: int = Field(ge=1, strict=True)


class P4Record(VersionedEntity):
    """Validated P4 proposal; construction is neither commitment nor acceptance."""
    SCHEMA_STATUS: ClassVar[str] = "p4-proposal"
    NOTE: ClassVar[str] = "P4 invariants implemented; persistence and authority resolution remain application responsibilities."
    definition_status: Literal["p4-proposal"] = "p4-proposal"
    schema_version: Literal["p4-domain/v1"] = "p4-domain/v1"

    def ref(self) -> VersionRef:
        return VersionRef(identity=self.entity_id, version=self.record_version)

    def require_accepted_definition(self) -> None:
        raise NotImplementedError(f"{type(self).__name__}: P4 proposal requires semantic acceptance")


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must have a timezone")
    return value


def unique(values: tuple, label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {label}")


def exact(reference: VersionRef, record: P4Record) -> None:
    if reference != record.ref():
        raise ValueError("identity/version mismatch")
