"""Mechanical scaffold base. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScaffoldRecord(BaseModel):
    """Unreviewed placeholder. Not an accepted entity, resource base, authority or lifecycle model."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    SCHEMA_STATUS: ClassVar[str] = "unreviewed-scaffold"
    SOURCE_CLASS: ClassVar[str] = "ScaffoldRecord"
    NOTE: ClassVar[str] = "Definition pending review."

    entity_id: UUID | None = Field(default=None, description="Optional opaque identity placeholder; no resolver is implemented.")
    definition_status: Literal["unreviewed-scaffold"] = Field(default="unreviewed-scaffold", description="Fixed marker: not an accepted definition.")

    def require_accepted_definition(self) -> None:
        """Always fails until a reviewed implementation replaces the scaffold."""
        raise NotImplementedError(f"{type(self).__name__}: definition and invariants are not implemented")
