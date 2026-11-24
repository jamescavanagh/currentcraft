"""Read-only REF export check; design: docs/architecture/GRAPH_SOURCE_CHECK.md."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

MAX_BYTES = 64 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z")
REF = re.compile(r"ref_[A-Za-z0-9_-]{1,120}\Z")
PROFILE = set("profile_id version heading_pattern max_file_bytes max_pages max_extracted_chars max_chunk_chars coverage coverage_reason".split())
BUNDLE = set("schema_version document_id source_name source_format coverage coverage_reason source_sha256 extractor_name extractor_version profile_sha256 pages nodes payload_sha256".split())
NODE = set("node_id kind parent_node_id ordinal depth page_number start_offset end_offset section_key title section_level".split())
KINDS = {"document": "reference_document", "section": "reference_section", "passage": "reference_passage"}


class CheckFailure(Exception):
    """Only fixed diagnostic codes may leave this checker."""


def require(condition, code):
    if not condition:
        raise CheckFailure(code)


def closed(value, keys):
    require(type(value) is dict and set(value) == set(keys), "invalid_shape")


def positive(value):
    return type(value) is int and value > 0


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def invalid_constant(_value):
    raise CheckFailure("invalid_json")


def decode(raw):
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def read_file(root, relative):
    require(type(relative) is str and relative and "\\" not in relative, "unsafe_path")
    parts = relative.split("/")
    require(all(part not in {"", ".", ".."} for part in parts), "unsafe_path")
    base = Path(root).absolute()
    require(base.resolve(strict=True) == base and base.is_dir(), "unsafe_root")
    directory = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=directory)
            os.close(directory)
            directory = nxt
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode), "not_regular_file")
        require(info.st_size <= MAX_BYTES, "file_limit")
        chunks = bytearray()
        while len(chunks) <= MAX_BYTES:
            block = os.read(fd, min(65536, MAX_BYTES + 1 - len(chunks)))
            if not block:
                break
            chunks.extend(block)
        require(len(chunks) <= MAX_BYTES, "file_limit")
        return bytes(chunks)
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def pinned(root, pin):
    closed(pin, {"path", "sha256"})
    require(type(pin["sha256"]) is str and HEX.fullmatch(pin["sha256"]), "invalid_digest")
    raw = read_file(root, pin["path"])
    require(sha(raw) == pin["sha256"], "file_hash_mismatch")
    return raw


def expected_document(bundle, profile, source, document_id):
    closed(profile, PROFILE)
    closed(bundle, BUNDLE)
    require(bundle["schema_version"] == "currentcraft-ref-document/v1", "unsupported_bundle")
    require(type(document_id) is str and REF.fullmatch(document_id), "invalid_document")
    require(bundle["document_id"] == document_id, "document_mismatch")
    require(bundle["source_sha256"] == sha(source), "source_hash_mismatch")
    require(bundle["profile_sha256"] == sha(canonical(profile)), "profile_hash_mismatch")
    payload = {k: v for k, v in bundle.items() if k != "payload_sha256"}
    require(bundle["payload_sha256"] == sha(canonical(payload)), "payload_hash_mismatch")
    require(bundle["coverage"] in {"full", "partial", "unknown"}, "invalid_coverage")
    require((bundle["coverage"], bundle["coverage_reason"]) ==
            (profile["coverage"], profile["coverage_reason"]), "coverage_mismatch")
    require(bundle["coverage"] != "partial" or
            (type(bundle["coverage_reason"]) is str and bundle["coverage_reason"].strip()),
            "invalid_coverage")
    pages = bundle["pages"]
    nodes = bundle["nodes"]
    require(type(pages) is list and 0 < len(pages) <= 20000, "invalid_pages")
    require(type(nodes) is list and 0 < len(nodes) <= 100000, "invalid_nodes")
    for index, page in enumerate(pages, 1):
        closed(page, {"page_number", "text"})
        require(type(page["page_number"]) is int and page["page_number"] == index
                and type(page["text"]) is str and len(page["text"]) <= 2000000, "invalid_page")
    fmt = bundle["source_format"]
    require(fmt in {"text", "markdown", "owl", "pdf"}, "unsupported_format")
    if fmt != "pdf":
        require(len(pages) == 1 and pages[0]["text"] == source.decode("utf-8-sig"),
                "source_text_mismatch")
    expected, parents = {}, {}
    for index, node in enumerate(nodes, 1):
        closed(node, NODE)
        nid, kind = node["node_id"], node["kind"]
        require(type(nid) is str and REF.fullmatch(nid) and nid not in expected, "invalid_node_identity")
        require(kind in KINDS and type(node["title"]) is str and node["title"], "invalid_node")
        require(type(node["ordinal"]) is int and node["ordinal"] == index, "invalid_ordinal")
        require(type(node["depth"]) is int and 0 <= node["depth"] <= 100, "invalid_depth")
        parent = node["parent_node_id"]
        if index == 1:
            require(kind == "document" and nid == document_id and parent is None
                    and node["depth"] == 0 and all(node[k] is None for k in
                    ("page_number", "start_offset", "end_offset", "section_key", "section_level")),
                    "invalid_root")
            text = ""
        else:
            require(kind != "document" and type(parent) is str and parent in expected,
                    "invalid_parent")
            require(expected[parent]["fields"]["node_kind"] != "passage"
                    and node["depth"] == expected[parent]["fields"]["depth"] + 1, "invalid_parent")
            page, start, end = node["page_number"], node["start_offset"], node["end_offset"]
            require(positive(page) and page <= len(pages) and type(start) is int
                    and type(end) is int and 0 <= start < end <= len(pages[page-1]["text"]),
                    "invalid_span")
            text = pages[page-1]["text"][start:end]
            parents[nid] = parent
        if kind == "section":
            require(type(node["section_key"]) is str and node["section_key"]
                    and positive(node["section_level"]), "invalid_section")
        else:
            require(node["section_key"] is None and node["section_level"] is None,
                    "invalid_section")
        fields = {k: bundle[k] for k in ("schema_version", "source_sha256", "payload_sha256",
                  "profile_sha256", "extractor_name", "extractor_version", "coverage", "coverage_reason")}
        fields.update({k: node[k] for k in ("depth", "ordinal", "page_number", "start_offset",
                      "end_offset", "section_key", "section_level")})
        fields.update(node_kind=kind, source_name=bundle["source_name"] if kind == "document" else None,
                      epistemic_scope="source_literal_candidate")
        expected[nid] = {"object_id": nid, "kind": KINDS[kind], "title": node["title"],
                         "text": text, "fields": fields,
                         "provenance": {"source_id": document_id, "content_sha256": sha(source),
                                        "adapter": "ref_document_tree", "adapter_version": "1.0"}}
    return expected, parents


def check(root, manifest_path, manifest_sha256):
    require(type(manifest_sha256) is str and HEX.fullmatch(manifest_sha256), "invalid_digest")
    manifest = decode(pinned(root, {"path": manifest_path, "sha256": manifest_sha256}))
    closed(manifest, {"schema_version", "graph", "documents"})
    require(manifest["schema_version"] == "currentcraft-graph-check/v1", "unsupported_manifest")
    gp = manifest["graph"]
    closed(gp, {"path", "sha256", "snapshot_id"})
    require(type(gp["snapshot_id"]) is str and 0 < len(gp["snapshot_id"]) <= 160, "invalid_snapshot")
    graph = decode(pinned(root, {k: gp[k] for k in ("path", "sha256")}))
    closed(graph, {"schema_version", "snapshot_id", "documents", "nodes", "edges"})
    require(graph["schema_version"] == "currentcraft-ref-graph-export/v1", "unsupported_export")
    require(graph["snapshot_id"] == gp["snapshot_id"], "snapshot_mismatch")
    docs = manifest["documents"]
    require(type(docs) is list and 0 < len(docs) <= 1000, "invalid_selection")
    expected, parents, doc_ids = {}, {}, []
    for doc in docs:
        closed(doc, {"document_id", "source", "profile", "bundle"})
        did = doc["document_id"]
        require(type(did) is str and did not in doc_ids, "duplicate_document")
        source = pinned(root, doc["source"])
        profile = decode(pinned(root, doc["profile"]))
        bundle = decode(pinned(root, doc["bundle"]))
        enodes, eparents = expected_document(bundle, profile, source, did)
        require(not set(expected).intersection(enodes), "duplicate_node")
        expected.update(enodes)
        parents.update(eparents)
        doc_ids.append(did)
    require(type(graph["documents"]) is list and all(type(x) is str for x in graph["documents"])
            and len(graph["documents"]) == len(doc_ids)
            and set(graph["documents"]) == set(doc_ids), "selection_mismatch")
    require(type(graph["nodes"]) is list and len(graph["nodes"]) == len(expected), "node_set_mismatch")
    versions = {}
    for node in graph["nodes"]:
        closed(node, {"object_id", "version_no", "kind", "title", "text", "fields", "provenance"})
        nid = node["object_id"]
        require(type(nid) is str and nid in expected and nid not in versions, "node_set_mismatch")
        require(positive(node["version_no"]), "invalid_version")
        actual = {k:v for k,v in node.items() if k != "version_no"}
        # Canonical JSON prevents Python's True == 1 equality from masking type drift.
        require(canonical(actual) == canonical(expected[nid]), "node_content_mismatch")
        versions[nid] = node["version_no"]
    require(type(graph["edges"]) is list and len(graph["edges"]) == len(parents), "edge_set_mismatch")
    seen = set()
    for edge in graph["edges"]:
        closed(edge, {"src_id", "rel_type", "dst_id", "src_version", "dst_version", "evidence"})
        src, dst = edge["src_id"], edge["dst_id"]
        require(type(src) is str and type(dst) is str and src in parents
                and parents[src] == dst and src not in seen and edge["rel_type"] == "part_of"
                and edge["evidence"] == "reference_tree.parent_node_id", "edge_set_mismatch")
        require(positive(edge["src_version"]) and positive(edge["dst_version"])
                and edge["src_version"] == versions[src]
                and edge["dst_version"] == versions[dst], "edge_version_mismatch")
        seen.add(src)
    return {"status": "match", "code": "selected_snapshot_matches_pins",
            "documents": len(doc_ids), "nodes": len(versions), "edges": len(seen)}


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise CheckFailure("invalid_arguments")


def main(argv=None):
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--root", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        args = parser.parse_args(argv)
        result = check(args.root, args.manifest, args.manifest_sha256)
    except CheckFailure as exc:
        result = {"status": "fail", "code": str(exc)}
    except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError):
        result = {"status": "fail", "code": "invalid_input_or_unavailable"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "match" else 1


if __name__ == "__main__":
    sys.exit(main())
