"""Versioned vocabulary identity; design: docs/domain/P0_P3_CAPTURE.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text


class ReferenceSet(VersionedEntity):
    """Source vocabulary linked to, but not selected instead of, ReferenceDictionary."""
    SOURCE_CLASS: ClassVar[str] = "ReferenceSet"
    kind: Literal["reference_set"] = "reference_set"
    dictionary_id: Text
    dictionary_version: Text
    source_owner: Fact[Text] = Field(default_factory=unknown)
