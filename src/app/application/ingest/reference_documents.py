"""Private source-document tree contracts. Source text belongs only in a private REF snapshot."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal

from pydantic import Field, PositiveInt, TypeAdapter, model_validator

from app.application.common.contracts import _Frozen

SCHEMA_VERSION = "currentcraft-ref-document/v1"
_ID = r"^ref_[A-Za-z0-9_-]{1,120}$"
_MAX_PAGE_CHARS = 2_000_000
_MAX_NODES = 100_000


def _ordered(value):
    """Stable contract serialization through Pydantic, not an application-layer JSON parser."""
    if isinstance(value, dict):
        return {key: _ordered(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_ordered(item) for item in value]
    return value


class ReferenceIngestProfile(_Frozen):
    """Private, reviewed extraction settings; source text cannot select executable behavior."""
    profile_id: str = Field(min_length=1, max_length=120, pattern=r".*\S.*", description="Private profile handle.")
    version: str = Field(min_length=1, max_length=80, pattern=r".*\S.*", description="Exact profile revision.")
    heading_pattern: str | None = Field(default=None, max_length=256, description="Trusted regex with named key and title groups; not read from the source document.")
    max_file_bytes: PositiveInt = Field(default=32 * 1024 * 1024, le=64 * 1024 * 1024, description="Maximum source-file size.")
    max_pages: PositiveInt = Field(default=2_000, le=20_000, description="Maximum extracted page count.")
    max_extracted_chars: PositiveInt = Field(default=20_000_000, le=100_000_000, description="Maximum total extracted characters.")
    max_chunk_chars: PositiveInt = Field(default=18_000, ge=256, le=20_000, description="Maximum passage length per graph node.")

    @model_validator(mode="after")
    def valid_heading_rule(self):
        if self.heading_pattern is not None:
            try:
                rule = re.compile(self.heading_pattern)
            except re.error as exc:
                raise ValueError("invalid private heading rule") from exc
            if not {"key", "title"}.issubset(rule.groupindex):
                raise ValueError("heading rule requires named key and title groups")
        return self

    def digest(self) -> str:
        raw = TypeAdapter(dict).dump_json(_ordered(self.model_dump(mode="json")))
        return hashlib.sha256(raw).hexdigest()


class ReferencePage(_Frozen):
    """Exact text emitted by one deterministic extractor page, retained only in private JSON."""
    page_number: PositiveInt = Field(strict=True, description="One-based extracted page number.")
    text: str = Field(max_length=_MAX_PAGE_CHARS, description="Exact extracted page text; private source-derived content.")


class ReferenceNode(_Frozen):
    """One source-literal tree node with offsets into an exact extracted page."""
    node_id: str = Field(pattern=_ID, description="Opaque node handle; the document root reuses its manifest-supplied source handle.")
    kind: Literal["document", "section", "passage"] = Field(description="Structural source unit, not interpreted meaning.")
    parent_node_id: str | None = Field(default=None, pattern=_ID, description="Containing node; null only for the document root.")
    ordinal: PositiveInt = Field(strict=True, description="Stable order within the emitted tree.")
    depth: int = Field(ge=0, le=100, strict=True, description="Tree depth; zero for the document root.")
    page_number: PositiveInt | None = Field(default=None, strict=True, description="One-based page for source spans.")
    start_offset: int | None = Field(default=None, ge=0, strict=True, description="Inclusive Unicode-codepoint offset in the extracted page.")
    end_offset: int | None = Field(default=None, gt=0, strict=True, description="Exclusive Unicode-codepoint offset in the extracted page.")
    section_key: str | None = Field(default=None, max_length=120, description="Literal heading key, when a trusted profile recognizes one.")
    title: str = Field(min_length=1, max_length=500, description="Source heading or neutral structural label; private when source-derived.")
    section_level: int | None = Field(default=None, ge=1, le=100, strict=True, description="Heading-number depth when available; does not imply semantics.")

    @model_validator(mode="after")
    def span_shape(self):
        if self.kind == "document":
            if self.parent_node_id is not None or self.depth != 0 or self.page_number is not None or self.start_offset is not None or self.end_offset is not None:
                raise ValueError("document root has no parent or page span")
            if self.section_key is not None or self.section_level is not None:
                raise ValueError("document root is not a section")
        else:
            if self.parent_node_id is None or self.depth == 0 or self.page_number is None or self.start_offset is None or self.end_offset is None:
                raise ValueError("non-root nodes need a parent and exact page span")
            if self.end_offset <= self.start_offset:
                raise ValueError("source span must be nonempty")
        if self.kind == "section":
            if not self.section_key or self.section_level is None:
                raise ValueError("section needs its literal key and level")
        elif self.section_key is not None or self.section_level is not None:
            raise ValueError("only sections have section keys and levels")
        return self


class ReferenceDocumentBundle(_Frozen):
    """Closed source-plus-tree snapshot. It is not a policy interpretation or approval record."""
    schema_version: Literal["currentcraft-ref-document/v1"] = Field(default=SCHEMA_VERSION, description="Private reference document bundle schema.")
    document_id: str = Field(pattern=_ID, description="Opaque source/revision handle supplied by the private REF manifest; never inferred from filename or bytes.")
    source_name: str = Field(min_length=1, max_length=1024, description="Private source-relative locator label.")
    source_format: Literal["pdf", "text", "markdown"] = Field(description="Read-only source format.")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256 of the exact source bytes.")
    extractor_name: Literal["pypdf", "utf8"] = Field(description="Read-only extractor used.")
    extractor_version: str = Field(min_length=1, max_length=80, description="Exact extractor implementation version.")
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of the private extraction profile.")
    pages: tuple[ReferencePage, ...] = Field(min_length=1, max_length=20_000, description="Exact extracted page text, private by default.")
    nodes: tuple[ReferenceNode, ...] = Field(min_length=1, max_length=_MAX_NODES, description="Source-literal hierarchy and spans.")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of the canonical bundle payload excluding this field.")

    @model_validator(mode="after")
    def closed_tree(self):
        if tuple(p.page_number for p in self.pages) != tuple(range(1, len(self.pages) + 1)):
            raise ValueError("page numbers must be contiguous and one-based")
        if self.nodes[0].kind != "document" or sum(n.kind == "document" for n in self.nodes) != 1:
            raise ValueError("exactly one document root must be first")
        by_id: dict[str, ReferenceNode] = {}
        for node in self.nodes:
            if node.node_id in by_id:
                raise ValueError("node handles must be unique")
            if node.kind != "document":
                parent = by_id.get(node.parent_node_id or "")
                if parent is None:
                    raise ValueError("parents must appear before children")
                if node.depth != parent.depth + 1:
                    raise ValueError("node depth must follow its parent")
                if parent.kind == "passage":
                    raise ValueError("passages cannot contain children")
                if node.page_number > len(self.pages):
                    raise ValueError("node page is outside the extracted document")
                page = self.pages[node.page_number - 1].text
                if node.end_offset > len(page):
                    raise ValueError("node span exceeds its extracted page")
            by_id[node.node_id] = node
        return self

    def payload_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"payload_sha256"})
        raw = TypeAdapter(dict).dump_json(_ordered(payload))
        return hashlib.sha256(raw).hexdigest()


class ReferenceDocumentSelection(_Frozen):
    """Independent loader receipt. A receipt embedded in caller JSON is never trusted by itself."""
    document_id: str = Field(pattern=_ID, description="Document selected by the verified private loader.")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Selected source-byte digest.")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Selected semantic bundle digest.")
    json_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of the exact JSON file bytes.")
    selected_at: datetime = Field(description="Timezone-aware loader selection time.")
    method: Literal["private-file-sha256-and-payload/v1"] = Field(default="private-file-sha256-and-payload/v1", description="Independent private file and payload verification method.")

    @model_validator(mode="after")
    def aware_selection(self):
        if self.selected_at.tzinfo is None or self.selected_at.utcoffset() is None:
            raise ValueError("selection time must be timezone-aware")
        return self


CONTRACTS = (ReferenceIngestProfile, ReferencePage, ReferenceNode, ReferenceDocumentBundle, ReferenceDocumentSelection)
