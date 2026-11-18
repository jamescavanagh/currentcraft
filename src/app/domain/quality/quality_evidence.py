"""Canonical domain evidence record. Design: docs/domain/V1_DOMAIN.md."""
from datetime import datetime
from typing import ClassVar, Literal
from pydantic import Field, model_validator
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, TimeWindow, unknown
from app.domain.shared.identity import Text


class QualityEvidence(VersionedEntity):
    """Source assertion and time provenance; never implicit human authority."""
    SOURCE_CLASS: ClassVar[str] = 'QualityEvidence'
    kind: Literal["quality_evidence"] = "quality_evidence"
    source: Text
    source_version: Text
    locator: Text
    status: Literal["observed", "inferred", "unknown"]
    recorded_at: datetime
    valid_time: Fact[TimeWindow] = Field(default_factory=unknown)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_sha256_missing_reason: Text | None = "not supplied"

    @model_validator(mode="after")
    def check_provenance(self):
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        if (self.source_sha256 is None) != (self.source_sha256_missing_reason is not None):
            raise ValueError("source hash is known or has a missing reason")
        return self
