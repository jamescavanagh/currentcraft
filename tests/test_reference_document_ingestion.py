"""Synthetic-only acceptance for private reference-document ingestion."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.application.ingest.reference_documents import CONTRACTS, ReferenceIngestProfile
from app.infrastructure.ingest.reference_documents import (
    build_bundle, hydrate_bundle, ingest_and_hydrate, load_bundle, write_bundle,
)
from app.infrastructure.persistence.memory import MemoryStore

WHEN = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
SOURCE_HANDLE = "ref_synthetic_doc_001"
PROFILE = ReferenceIngestProfile(
    profile_id="synthetic-profile", version="1",
    heading_pattern=r"(?P<key>\d+(?:\.\d+)*)\s+(?P<title>.+)",
)
TEXT = """Title\n\n1 Scope\nOpening paragraph.\n\n1.1 Boundary\nNested evidence.\n\n2 Requirements\nLast paragraph.\n"""


class ReferenceDocumentIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "private"
        self.root.mkdir()
        self.source = self.root / "source.txt"
        self.source.write_text(TEXT, encoding="utf-8")
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def test_extracts_exact_text_and_nested_candidate_tree(self):
        bundle = build_bundle(self.root, "source.txt", SOURCE_HANDLE, self.digest, PROFILE)
        self.assertEqual(bundle.pages[0].text, TEXT)
        self.assertEqual(bundle.document_id, bundle.nodes[0].node_id)
        sections = [node for node in bundle.nodes if node.kind == "section"]
        self.assertEqual([node.section_key for node in sections], ["1", "1.1", "2"])
        self.assertEqual(sections[1].parent_node_id, sections[0].node_id)
        for node in bundle.nodes:
            if node.kind != "document":
                span = bundle.pages[node.page_number - 1].text[node.start_offset:node.end_offset]
                self.assertTrue(span)
        self.assertEqual(bundle.payload_sha256, bundle.payload_digest())

    def test_end_to_end_private_json_to_graph_is_atomic_and_idempotent(self):
        store = MemoryStore()
        bundle, first = ingest_and_hydrate(
            self.root, "source.txt", SOURCE_HANDLE, "derived/source.json", self.digest, PROFILE, store, WHEN)
        self.assertFalse(first.replayed)
        self.assertEqual(len(first.object_ids), len(bundle.nodes))
        private_json = self.root / "derived/source.json"
        self.assertEqual(json.loads(private_json.read_text())["source_sha256"], self.digest)
        self.assertEqual(private_json.stat().st_mode & 0o777, 0o600)
        second_loaded = load_bundle(self.root, "derived/source.json",
                                    hashlib.sha256(private_json.read_bytes()).hexdigest(), WHEN)
        second = hydrate_bundle(second_loaded, store, WHEN)
        self.assertTrue(second.replayed)
        with store() as uow:
            root = uow.objects.get(bundle.nodes[0].node_id)
            self.assertEqual(root.kind, "reference_document")
            child = next(n for n in bundle.nodes if n.kind == "section")
            self.assertEqual(uow.objects.get(child.node_id).relations[0].type, "part_of")
            self.assertEqual(len(uow.objects.by_kind("reference_section")), 3)

    def test_source_and_json_hashes_are_pinned(self):
        with self.assertRaisesRegex(ValueError, "source document SHA-256 mismatch"):
            build_bundle(self.root, "source.txt", SOURCE_HANDLE, "0" * 64, PROFILE)
        bundle = build_bundle(self.root, "source.txt", SOURCE_HANDLE, self.digest, PROFILE)
        write_bundle(self.root, "derived/source.json", bundle)
        with self.assertRaisesRegex(ValueError, "bundle file SHA-256 mismatch"):
            load_bundle(self.root, "derived/source.json", "0" * 64, WHEN)

    def test_profile_and_hierarchy_are_closed(self):
        with self.assertRaises(ValidationError):
            ReferenceIngestProfile(profile_id="x", version="1", heading_pattern="(broken")
        with self.assertRaises(ValidationError):
            ReferenceIngestProfile(profile_id="x", version="1", heading_pattern=r"(?P<key>x)(?P<other>y)")
        bundle = build_bundle(self.root, "source.txt", SOURCE_HANDLE, self.digest, PROFILE)
        data = bundle.model_dump(mode="json")
        data["nodes"][1]["parent_node_id"] = "ref_" + "0" * 32
        with self.assertRaises(ValidationError):
            type(bundle).model_validate(data)

    def test_private_root_and_path_escape_are_enforced(self):
        for relative in ("../outside.txt", "/tmp/outside.txt", "nested\\escape.txt"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                build_bundle(self.root, relative, SOURCE_HANDLE, self.digest, PROFILE)
        public_root = Path(self.temp.name) / "public"
        public_root.mkdir()
        with self.assertRaisesRegex(ValueError, "private directory"):
            write_bundle(public_root, "leak.json", build_bundle(self.root, "source.txt", SOURCE_HANDLE, self.digest, PROFILE))

    def test_duplicate_json_keys_are_rejected(self):
        duplicate = self.root / "duplicate.json"
        duplicate.write_text('{"a": 1, "a": 2}', encoding="utf-8")
        raw_hash = hashlib.sha256(duplicate.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            load_bundle(self.root, "duplicate.json", raw_hash, WHEN)

    def test_json_payload_tampering_and_naive_selection_time_fail_closed(self):
        bundle = build_bundle(self.root, "source.txt", SOURCE_HANDLE, self.digest, PROFILE)
        write_bundle(self.root, "derived/source.json", bundle)
        path = self.root / "derived/source.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["source_name"] = "changed.txt"
        path.write_text(json.dumps(payload), encoding="utf-8")
        changed_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "payload SHA-256 mismatch"):
            load_bundle(self.root, "derived/source.json", changed_sha, WHEN)
        write_bundle(self.root, "derived/source.json", bundle)
        valid_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            load_bundle(self.root, "derived/source.json", valid_sha, datetime(2026, 11, 21))

    def test_contracts_publish_closed_json_schemas(self):
        for model in CONTRACTS:
            with self.subTest(model=model.__name__):
                schema = model.model_json_schema()
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
