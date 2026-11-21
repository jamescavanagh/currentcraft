"""Hierarchical evidence values (design: docs/architecture/EVIDENCE_CHUNKS.md).

No source text or identity generation. Locators resolve privately, server-side.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.application.common.contracts import _Frozen

SCHEMA_VERSION = "currentcraft-evidence/v1"
_HANDLE = r"^[A-Za-z0-9_-]{1,200}$"


def _handle(description: str):
    return Field(pattern=_HANDLE, description=description)


class EvidenceTextOffsets(_Frozen):
    """A nonempty half-open span in the declared extractor output."""

    start: int = Field(ge=0, strict=True, description="Zero-based inclusive start in the declared unit.")
    end: int = Field(gt=0, strict=True, description="Exclusive end, strictly greater than start.")
    unit: Literal["unicode_codepoints", "bytes"] = Field(description="Offset unit in the exact extractor output.")

    @model_validator(mode="after")
    def _ordered(self):
        if self.end <= self.start:
            raise ValueError("offset end must exceed start")
        return self


class EvidenceCellRange(_Frozen):
    """One-based inclusive rectangular range; sheet identity is opaque."""

    sheet_id: str = _handle("Opaque worksheet handle, never its original name.")
    first_row: int = Field(ge=1, strict=True, description="First included row, one-based.")
    last_row: int = Field(ge=1, strict=True, description="Last included row, not before first_row.")
    first_column: int = Field(ge=1, strict=True, description="First included column, one-based.")
    last_column: int = Field(ge=1, strict=True, description="Last included column, not before first_column.")

    @model_validator(mode="after")
    def _ordered(self):
        if self.last_row < self.first_row or self.last_column < self.first_column:
            raise ValueError("cell range bounds must be ordered")
        return self


class EvidenceProvenance(_Frozen):
    """Internal provenance descriptors, not an HTTP projection or source content."""

    source_locator: str = _handle("Opaque locator for an immutable source unit; resolves privately server-side.")
    extractor_name: str = Field(min_length=1, max_length=200, pattern=r".*\S.*",
                                description="Extractor implementation name, not a source identifier.")
    extractor_version: str = Field(min_length=1, max_length=200, pattern=r".*\S.*",
                                   description="Exact extractor version that produced the located output.")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256 of the extractor configuration.")
    page_number: int | None = Field(default=None, ge=1, strict=True, description="One-based page number, for page chunks only.")
    offsets: EvidenceTextOffsets | None = Field(default=None, description="Half-open span in the declared extractor output.")
    cells: EvidenceCellRange | None = Field(default=None, description="Inclusive worksheet range, mutually exclusive with offsets.")

    @model_validator(mode="after")
    def _one_coordinate_system(self):
        if self.offsets is not None and self.cells is not None:
            raise ValueError("offsets and cells are mutually exclusive")
        return self


class EvidenceChunk(_Frozen):
    """One located evidence unit. Presence or relevance is never approval."""

    schema_version: Literal["currentcraft-evidence/v1"] = Field(default=SCHEMA_VERSION, description="Evidence payload schema version.")
    chunk_id: str = _handle("Opaque evaluation item handle; supplied unchanged, not generated here.")
    kind: Literal["page", "sheet", "bom_row", "email", "chat_thread"] = Field(description="Source-unit kind, not an approval or document lifecycle state.")
    file_id: str = _handle("Explicit opaque source file identity; companion PDF identity for drawing content.")
    revision_id: str = _handle("Opaque immutable revision reference supplied by the document identity lane.")
    project_id: str = _handle("Explicit opaque project binding; never inferred from source content.")
    parent_chunk_id: str | None = Field(default=None, pattern=_HANDLE, description="Containing sheet chunk for a BOM row; absent on roots.")
    provenance: EvidenceProvenance = Field(description="Source locator, coordinates and exact extractor version/configuration.")

    @model_validator(mode="after")
    def _shape(self):
        p = self.provenance
        if self.parent_chunk_id == self.chunk_id:
            raise ValueError("a chunk cannot parent itself")
        if self.kind == "page":
            if p.page_number is None or p.cells is not None:
                raise ValueError("page requires page number and forbids cells")
        elif self.kind in ("sheet", "bom_row"):
            if p.cells is None or p.page_number is not None or p.offsets is not None:
                raise ValueError("worksheet chunks require cells only")
            if self.kind == "bom_row" and p.cells.first_row != p.cells.last_row:
                raise ValueError("BOM row must occupy exactly one row")
        elif p.offsets is None or p.cells is not None or p.page_number is not None:
            raise ValueError("email and chat thread require offsets only")
        if (self.kind == "bom_row") != (self.parent_chunk_id is not None):
            raise ValueError("only BOM rows have a required sheet parent")
        return self


class EvidenceChunkSet(_Frozen):
    """Closed hierarchy snapshot; does not establish completeness of any source."""

    schema_version: Literal["currentcraft-evidence/v1"] = Field(default=SCHEMA_VERSION, description="Evidence snapshot schema version.")
    chunks: tuple[EvidenceChunk, ...] = Field(description="All chunks in this closed snapshot; parents included, unique handles.")

    @model_validator(mode="after")
    def _hierarchy(self):
        by_id = {c.chunk_id: c for c in self.chunks}
        if len(by_id) != len(self.chunks):
            raise ValueError("chunk handles must be unique")
        for child in self.chunks:
            if child.parent_chunk_id is None:
                continue
            parent = by_id.get(child.parent_chunk_id)
            if parent is None:
                raise ValueError("parent chunk missing from snapshot")
            if parent.kind != "sheet":
                raise ValueError("BOM row parent must be a sheet")
            if (child.file_id, child.revision_id, child.project_id) != (
                    parent.file_id, parent.revision_id, parent.project_id):
                raise ValueError("parent and child bindings must match")
            c, p = child.provenance.cells, parent.provenance.cells
            if (c.sheet_id != p.sheet_id or c.first_row < p.first_row or c.last_row > p.last_row
                    or c.first_column < p.first_column or c.last_column > p.last_column):
                raise ValueError("BOM range must be contained in the same worksheet")
        return self


CONTRACTS = (EvidenceTextOffsets, EvidenceCellRange, EvidenceProvenance, EvidenceChunk, EvidenceChunkSet)
