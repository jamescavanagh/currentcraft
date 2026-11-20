"""Versioned reference value; design: docs/domain/P0_P3_CAPTURE.md."""
from typing import ClassVar, Literal
from uuid import UUID
from pydantic import Field, model_validator
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text


class ReferenceValue(VersionedEntity):
    """A code in one source vocabulary; deprecation never erases history."""
    SOURCE_CLASS: ClassVar[str] = "ReferenceValue"
    kind: Literal["reference_value"] = "reference_value"
    reference_set_id: UUID
    code: Fact[Text]
    deprecated: Fact[bool] = Field(default_factory=unknown)
    superseded_by_id: Fact[UUID] = Field(default_factory=unknown)

    @model_validator(mode="after")
    def no_self_supersession(self):
        if self.superseded_by_id.value == self.entity_id:
            raise ValueError("reference value cannot supersede itself")
        return self
