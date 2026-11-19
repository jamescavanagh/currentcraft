"""Canonical domain evidence record. Design: docs/domain/V1_DOMAIN.md."""
from datetime import datetime
from typing import ClassVar, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, TimeWindow, unknown
from app.domain.shared.identity import Text, EvidenceId


class Derivation(BaseModel):
    """Explicit input-to-conclusion assertion; method locator is data, not executable code."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    method_ref: Text
    input_evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_inputs(self):
        if len(set(self.input_evidence_ids)) != len(self.input_evidence_ids):
            raise ValueError("duplicate derivation input")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler.resolve_ref_schema(handler(core_schema))
        schema["properties"]["input_evidence_ids"]["uniqueItems"] = True
        return schema


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
    derivation: Derivation | None = None

    @model_validator(mode="after")
    def check_provenance(self):
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        if (self.source_sha256 is None) != (self.source_sha256_missing_reason is not None):
            raise ValueError("source hash is known or has a missing reason")
        if (self.status == "inferred") != (self.derivation is not None):
            raise ValueError("inferred assertion requires derivation; other statuses have none")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler.resolve_ref_schema(handler(core_schema))
        schema.setdefault("allOf", []).extend([
            {"oneOf": [
                {"properties": {"source_sha256": {"type": "null"},
                    "source_sha256_missing_reason": {"type": "string", "minLength": 1, "pattern": r"\S"}}},
                {"required": ["source_sha256", "source_sha256_missing_reason"],
                 "properties": {"source_sha256": {"type": "string"},
                    "source_sha256_missing_reason": {"type": "null"}}}
            ]},
            {"if": {"properties": {"status": {"const": "inferred"}}, "required": ["status"]},
             "then": {"required": ["derivation"], "properties": {"derivation": {"not": {"type": "null"}}}},
             "else": {"properties": {"derivation": {"type": "null"}}}}
        ])
        return schema
