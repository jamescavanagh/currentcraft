"""Private source document -> exact JSON -> existing source-object graph hydration."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import weakref
from xml.parsers import expat
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable

from app.application.ingest.contracts import DomainObject, Provenance, TypedRelation
from app.application.ingest.reference_documents import (
    ReferenceDocumentBundle, ReferenceDocumentSelection, ReferenceIngestProfile,
    ReferenceNode, ReferencePage,
)
from app.application.persistence.contracts import CommandRecord

MAX_JSON_BYTES = 128 * 1024 * 1024
RDF_POLICY = "rdfxml-stream/1"
RDF_CHUNK_CHARS = 16_384
RDF_MAX_DEPTH = 128
RDF_MAX_ELEMENTS = 100_000
RDF_MAX_ATTRIBUTES = 64
RDF_MAX_ATTRIBUTE_CHARS = 16_384
_RDF_ROOT = "http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"


@dataclass(frozen=True, eq=False)
class LoadedReferenceDocument:
    bundle: ReferenceDocumentBundle
    selection: ReferenceDocumentSelection


_ISSUED = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class HydrationResult:
    document_id: str
    payload_sha256: str
    object_ids: tuple[str, ...]
    replayed: bool


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_path(root: Path, relative: str, *, must_exist: bool) -> tuple[Path, Path]:
    if not root.is_absolute():
        raise ValueError("private REF root must be explicit and absolute")
    base = root.resolve(strict=True)
    if base.name != "private" or not base.is_dir():
        raise ValueError("configured REF root must be a private directory named 'private'")
    rel = Path(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        raise ValueError("path must be a relative path contained by the private REF root")
    current = base
    for part in rel.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("symlinks are not accepted in private REF paths")
    if must_exist:
        path = (base / rel).resolve(strict=True)
        if not path.is_relative_to(base) or not path.is_file():
            raise ValueError("source must be a regular file within the private REF root")
        return base, path
    parent = (base / rel.parent).resolve(strict=False)
    if not parent.is_relative_to(base):
        raise ValueError("output path must stay within the private REF root")
    parent.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in (parent, *parent.parents) if p != base.parent and p != base):
        raise ValueError("symlinks are not accepted in private REF output paths")
    path = parent / rel.name
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("output must be a regular JSON file path")
    return base, path


def _validate_rdf_xml(text: str) -> None:
    """Bounded-event source validation only: no tree, resolver, imports or reasoning."""
    parser = expat.ParserCreate(namespace_separator="}")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    depth = elements = namespace_declarations = 0

    def forbidden(*_args):
        raise ValueError("ontology declarations and external entities are not permitted")

    def start(name, attributes):
        nonlocal depth, elements, namespace_declarations
        depth += 1
        elements += 1
        if elements == 1 and name != _RDF_ROOT:
            raise ValueError("ontology source must have an RDF/XML root")
        if depth > RDF_MAX_DEPTH:
            raise ValueError("ontology source exceeds the XML depth limit")
        if elements > RDF_MAX_ELEMENTS:
            raise ValueError("ontology source exceeds the XML element limit")
        if len(attributes) + namespace_declarations > RDF_MAX_ATTRIBUTES:
            raise ValueError("ontology source exceeds the XML attribute limit")
        namespace_declarations = 0
        if any(len(value) > RDF_MAX_ATTRIBUTE_CHARS for value in attributes.values()):
            raise ValueError("ontology source exceeds the XML attribute value limit")

    def end(_name):
        nonlocal depth
        depth -= 1

    def namespace(_prefix, uri):
        nonlocal namespace_declarations
        namespace_declarations += 1
        if namespace_declarations > RDF_MAX_ATTRIBUTES:
            raise ValueError("ontology source exceeds the XML attribute limit")
        if len(uri or "") > RDF_MAX_ATTRIBUTE_CHARS:
            raise ValueError("ontology source exceeds the XML attribute value limit")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartNamespaceDeclHandler = namespace
    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    malformed = False
    try:
        for offset in range(0, len(text), RDF_CHUNK_CHARS):
            parser.Parse(text[offset:offset + RDF_CHUNK_CHARS], False)
        parser.Parse("", True)
    except expat.ExpatError:
        malformed = True
    # Raise outside the except block: no source-bearing parser exception chain.
    if malformed:
        raise ValueError("ontology source must be valid RDF/XML")


def _extract(raw: bytes, suffix: str, profile: ReferenceIngestProfile) -> tuple[tuple[str, ...], str, str, str]:
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF extraction requires the optional pdf dependency") from exc
        import io
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise ValueError("encrypted source PDFs are not accepted")
        if len(reader.pages) > profile.max_pages:
            raise ValueError("source exceeds the configured page limit")
        pages = tuple(page.extract_text() or "" for page in reader.pages)
        try:
            extractor_version = version("pypdf")
        except PackageNotFoundError:
            extractor_version = "unknown"
        fmt, extractor = "pdf", "pypdf"
    else:
        try:
            text = raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("text source must be valid UTF-8") from exc
        pages = (text,)
        fmt = "markdown" if suffix == ".md" else "text"
        extractor, extractor_version = "utf8", "stdlib-1"
        if suffix in {".owl", ".rdf"}:
            # Enforce decoded-source limits before allocating an XML parser.
            if len(text) > profile.max_extracted_chars:
                raise ValueError("extracted source exceeds the configured character limit")
            if len(text) > 2_000_000:
                raise ValueError("one extracted page exceeds the supported limit")
            _validate_rdf_xml(text)
            fmt, extractor, extractor_version = "owl", "rdfxml-source", RDF_POLICY
    if not pages or len(pages) > profile.max_pages:
        raise ValueError("source page count is outside the configured limit")
    if sum(len(page) for page in pages) > profile.max_extracted_chars:
        raise ValueError("extracted source exceeds the configured character limit")
    if any(len(page) > 2_000_000 for page in pages):
        raise ValueError("one extracted page exceeds the supported limit")
    return pages, fmt, extractor, extractor_version


def _node_id(document_id: str, source_sha: str, kind: str, page: int | None, start: int | None, end: int | None, ordinal: int) -> str:
    material = f"{document_id}|{source_sha}|{kind}|{page}|{start}|{end}|{ordinal}".encode()
    return "ref_" + hashlib.sha256(material).hexdigest()[:32]


def _heading_level(key: str) -> int:
    if re.fullmatch(r"\d+(?:\.\d+)*", key):
        return min(key.count(".") + 1, 100)
    return 1


def _make_tree(document_id: str, source_sha: str, source_name: str, pages: tuple[str, ...], profile: ReferenceIngestProfile) -> tuple[ReferenceNode, ...]:
    nodes: list[ReferenceNode] = []
    doc_id = document_id
    nodes.append(ReferenceNode(node_id=doc_id, kind="document", ordinal=1, depth=0,
                               title=source_name if len(source_name) <= 500 else "Reference document"))
    heading_rule = re.compile(profile.heading_pattern) if profile.heading_pattern else None
    # Active heading stack contains (numbering depth, node id, tree depth).
    stack: list[tuple[int, str, int]] = []
    ordinal = 1

    def add_span(kind: str, page_no: int, start: int, end: int, title: str,
                 parent_id: str, parent_depth: int, key: str | None = None, level: int | None = None):
        nonlocal ordinal
        if len(nodes) >= 100_000:
            raise ValueError("source exceeds the maximum node count")
        ordinal += 1
        nodes.append(ReferenceNode(
            node_id=_node_id(document_id, source_sha, kind, page_no, start, end, ordinal), kind=kind,
            parent_node_id=parent_id, ordinal=ordinal, depth=parent_depth + 1,
            page_number=page_no, start_offset=start, end_offset=end,
            section_key=key, title=title, section_level=level,
        ))
        return nodes[-1]

    for page_no, page_text in enumerate(pages, start=1):
        page_start = 0
        body_start: int | None = None
        body_end: int | None = None

        def flush_body():
            nonlocal body_start, body_end
            if body_start is None or body_end is None or body_end <= body_start:
                body_start = body_end = None
                return
            source = page_text[body_start:body_end]
            cursor = 0
            while cursor < len(source):
                stop = min(cursor + profile.max_chunk_chars, len(source))
                # Prefer a newline boundary without dropping or reordering any source characters.
                if stop < len(source):
                    newline = source.rfind("\n", cursor, stop)
                    if newline > cursor:
                        stop = newline + 1
                parent_id = stack[-1][1] if stack else doc_id
                parent_depth = stack[-1][2] if stack else 0
                add_span("passage", page_no, body_start + cursor, body_start + stop,
                         "Passage", parent_id, parent_depth)
                cursor = stop
            body_start = body_end = None

        for line in page_text.splitlines(keepends=True):
            content = line.rstrip("\r\n")
            line_end = page_start + len(content)
            next_start = page_start + len(line)
            if not content.strip():
                flush_body()
            else:
                match = heading_rule.fullmatch(content.strip()) if heading_rule and len(content) <= 2048 else None
                if match is not None:
                    flush_body()
                    key, title = match.group("key").strip(), match.group("title").strip()
                    if not title or len(title) > 500:
                        raise ValueError("recognized heading is empty or exceeds the title limit")
                    level = _heading_level(key)
                    while stack and stack[-1][0] >= level:
                        stack.pop()
                    parent_id = stack[-1][1] if stack else doc_id
                    parent_depth = stack[-1][2] if stack else 0
                    section = add_span("section", page_no, page_start, line_end, title,
                                       parent_id, parent_depth, key, level)
                    stack.append((level, section.node_id, section.depth))
                else:
                    if body_start is None:
                        body_start = page_start
                    body_end = line_end
            page_start = next_start
        flush_body()
    return tuple(nodes)


def build_bundle(root: Path, source_relative: str, source_handle: str, expected_source_sha256: str,
                 profile: ReferenceIngestProfile) -> ReferenceDocumentBundle:
    raw = _read_source_bytes(root, source_relative, profile.max_file_bytes)
    return build_bundle_from_bytes(raw, source_relative, source_handle, expected_source_sha256, profile)


def _read_source_bytes(root: Path, relative: str, limit: int) -> bytes:
    """Bounded regular-file selection through pinned no-follow directory descriptors."""
    base, _ = _safe_path(root, relative, must_exist=True)
    directory = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    source_fd = None
    try:
        parts = Path(relative).parts
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        source_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("source must be a regular file")
        if info.st_size > limit:
            raise ValueError("source file exceeds the configured byte limit")
        result = bytearray()
        while len(result) <= limit:
            block = os.read(source_fd, min(65_536, limit + 1 - len(result)))
            if not block:
                break
            result.extend(block)
        if len(result) > limit:
            raise ValueError("source file exceeds the configured byte limit")
        return bytes(result)
    finally:
        if source_fd is not None:
            os.close(source_fd)
        os.close(directory)


def build_bundle_from_bytes(raw: bytes, source_relative: str, source_handle: str,
                            expected_source_sha256: str, profile: ReferenceIngestProfile) -> ReferenceDocumentBundle:
    """Trusted primitive shared by the isolated worker and synthetic tests, not a sandbox."""
    suffix = Path(source_relative).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".owl", ".rdf"}:
        raise ValueError("supported source formats are PDF, UTF-8 text, Markdown and RDF/XML")
    if len(raw) > profile.max_file_bytes:
        raise ValueError("source file exceeds the configured byte limit")
    if not raw:
        raise ValueError("source document is empty")
    source_sha = _sha(raw)
    if source_sha != expected_source_sha256:
        raise ValueError("source document SHA-256 mismatch")
    page_texts, fmt, extractor, extractor_version = _extract(raw, suffix, profile)
    if not any(page.strip() for page in page_texts):
        raise ValueError("source has no extractable text; OCR is not included")
    pages = tuple(ReferencePage(page_number=i, text=text) for i, text in enumerate(page_texts, start=1))
    tree_profile = profile.model_copy(update={"heading_pattern": None}) if fmt == "owl" else profile
    nodes = _make_tree(source_handle, source_sha, source_relative, page_texts, tree_profile)
    provisional = ReferenceDocumentBundle(
        document_id=source_handle,
        source_name=source_relative, source_format=fmt, source_sha256=source_sha,
        coverage=profile.coverage, coverage_reason=profile.coverage_reason,
        extractor_name=extractor, extractor_version=extractor_version,
        profile_sha256=profile.digest(), pages=pages, nodes=nodes, payload_sha256="0" * 64,
    )
    return provisional.model_copy(update={"payload_sha256": provisional.payload_digest()})


def write_bundle(root: Path, output_relative: str, bundle: ReferenceDocumentBundle) -> str:
    """Atomically write source-derived JSON inside the explicitly configured private REF root."""
    if Path(output_relative).suffix.lower() != ".json":
        raise ValueError("private bundle output must be a JSON file")
    _, target = _safe_path(root, output_relative, must_exist=False)
    raw = bundle.model_dump_json().encode("utf-8")
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("serialized private bundle exceeds the JSON size limit")
    fd, temp_name = tempfile.mkstemp(prefix=".ref-ingest-", suffix=".tmp", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return _sha(raw)


def _closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def load_bundle(root: Path, json_relative: str, expected_json_sha256: str,
                selected_at: datetime) -> LoadedReferenceDocument:
    """Read an explicitly selected private JSON bundle and independently verify file and payload digests."""
    _, path = _safe_path(root, json_relative, must_exist=True)
    if path.suffix.lower() != ".json" or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("bundle must be a bounded JSON file")
    raw = path.read_bytes()
    json_sha = _sha(raw)
    if json_sha != expected_json_sha256:
        raise ValueError("private bundle file SHA-256 mismatch")
    def invalid_constant(value):
        raise ValueError("invalid JSON numeric constant")
    data = json.loads(raw, object_pairs_hook=_closed_object, parse_constant=invalid_constant)
    bundle = ReferenceDocumentBundle.model_validate(data)
    actual_payload_sha = bundle.payload_digest()
    if bundle.payload_sha256 != actual_payload_sha:
        raise ValueError("private bundle payload SHA-256 mismatch")
    if selected_at.tzinfo is None or selected_at.utcoffset() is None:
        raise ValueError("selection time must be timezone-aware")
    selection = ReferenceDocumentSelection(
        document_id=bundle.document_id, source_sha256=bundle.source_sha256,
        payload_sha256=actual_payload_sha, json_file_sha256=json_sha,
        selected_at=selected_at.isoformat(),
    )
    loaded = LoadedReferenceDocument(bundle, selection)
    # Identity-based, process-local loader capability. JSON receipts, direct
    # constructors and copied wrappers cannot mint it. Reload on process restart.
    _ISSUED[loaded] = (bundle.payload_sha256, selection.model_dump_json())
    return loaded


def _source_text(bundle: ReferenceDocumentBundle, node: ReferenceNode) -> str:
    if node.page_number is None:
        return ""
    page = bundle.pages[node.page_number - 1].text
    return page[node.start_offset:node.end_offset]


def _domain_objects(loaded: LoadedReferenceDocument, recorded_at: datetime) -> tuple[DomainObject, ...]:
    bundle, selection = loaded.bundle, loaded.selection
    if (selection.document_id, selection.source_sha256, selection.payload_sha256) != (
            bundle.document_id, bundle.source_sha256, bundle.payload_digest()):
        raise ValueError("loader selection does not match the exact bundle")
    if selection.method != "private-file-sha256-and-payload/v1":
        raise ValueError("unsupported private selection method")
    if _ISSUED.get(loaded) != (bundle.payload_sha256, selection.model_dump_json()):
        raise ValueError("hydration requires a loader-issued selection")
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("graph record time must be timezone-aware")
    provenance = Provenance(
        platform="private_ref", format="pdf" if bundle.source_format == "pdf" else "text",
        source_id=bundle.document_id, content_sha256=bundle.source_sha256,
        adapter="ref_document_tree", adapter_version="1.0", received_at=recorded_at,
    )
    by_id = {node.node_id: node for node in bundle.nodes}
    result = []
    for node in bundle.nodes:
        fields = {
            "schema_version": bundle.schema_version,
            "node_kind": node.kind,
            "source_sha256": bundle.source_sha256,
            "payload_sha256": bundle.payload_sha256,
            "profile_sha256": bundle.profile_sha256,
            "extractor_name": bundle.extractor_name,
            "extractor_version": bundle.extractor_version,
            "depth": node.depth,
            "ordinal": node.ordinal,
            "page_number": node.page_number,
            "start_offset": node.start_offset,
            "end_offset": node.end_offset,
            "section_key": node.section_key,
            "section_level": node.section_level,
            "source_name": bundle.source_name if node.kind == "document" else None,
            "epistemic_scope": "source_literal_candidate",
            "coverage": bundle.coverage,
            "coverage_reason": bundle.coverage_reason,
        }
        parent = by_id.get(node.parent_node_id or "")
        relations = (TypedRelation(type="part_of", target_id=parent.node_id,
                                   evidence="reference_tree.parent_node_id"),) if parent else ()
        result.append(DomainObject(
            object_id=node.node_id,
            kind={"document": "reference_document", "section": "reference_section", "passage": "reference_passage"}[node.kind],
            title=node.title, text=_source_text(bundle, node), fields=fields,
            relations=relations, provenance=provenance,
        ))
    return tuple(result)


def hydrate_bundle(loaded: LoadedReferenceDocument, uow_factory: Callable, recorded_at: datetime) -> HydrationResult:
    """Persist all source-literal nodes atomically through the existing graph/object UoW."""
    objects = _domain_objects(loaded, recorded_at)
    bundle = loaded.bundle
    command_id = "refdoc-" + bundle.payload_sha256[:48]
    with uow_factory() as uow:
        prior = uow.commands.get(command_id)
        if prior is not None:
            if prior.result_ref != bundle.document_id or prior.outcome != "applied":
                raise ValueError("idempotency key conflicts with an earlier command")
            return HydrationResult(bundle.document_id, bundle.payload_sha256,
                                   tuple(o.object_id for o in objects), True)
        versions = {}
        for obj in objects:
            relations = tuple(relation.model_copy(update={"target_version": versions[relation.target_id]})
                              for relation in obj.relations)
            pinned = obj.model_copy(update={"relations": relations})
            versions[obj.object_id] = uow.objects.put(pinned).version_no
        uow.commands.record(CommandRecord(
            command_id=command_id, command_type="private_ref_document_hydration.v1",
            outcome="applied", result_ref=bundle.document_id,
            recorded_at=recorded_at,
        ))
        uow.commit()
    return HydrationResult(bundle.document_id, bundle.payload_sha256,
                           tuple(o.object_id for o in objects), False)


def ingest_and_hydrate(root: Path, source_relative: str, source_handle: str, output_relative: str,
                       expected_source_sha256: str, profile: ReferenceIngestProfile,
                       uow_factory: Callable, recorded_at: datetime, *,
                       isolation=None) -> tuple[ReferenceDocumentBundle, HydrationResult]:
    """Hostile RDF entry point: mandatory Linux isolation; never falls back in-process."""
    from app.infrastructure.ingest.ref_isolation import IsolationFailure, LinuxIsolation, SOURCE_BYTES
    if type(isolation) is not LinuxIsolation:
        raise IsolationFailure("isolation_unavailable")
    isolation.check()
    source_valid = False
    try:
        if Path(source_relative).suffix.lower() not in {".owl", ".rdf"}:
            raise ValueError("format")
        raw = _read_source_bytes(root, source_relative, min(profile.max_file_bytes, SOURCE_BYTES))
        source_valid = bool(raw) and _sha(raw) == expected_source_sha256
    except (ValueError, OSError):
        pass
    if not source_valid:
        raise IsolationFailure("invalid_source")
    bundle = isolation.extract(raw, source_relative, source_handle, expected_source_sha256, profile)
    json_sha = write_bundle(root, output_relative, bundle)
    loaded = load_bundle(root, output_relative, json_sha, recorded_at)
    result = hydrate_bundle(loaded, uow_factory, recorded_at)
    return bundle, result
