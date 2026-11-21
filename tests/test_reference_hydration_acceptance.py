"""Acceptance suite: private REF source -> JSON bundle -> graph hydration (PR #43).

Synthetic sources only. No real standards, mappings or extracted private content.

Every criterion runs against each unit-of-work implementation available:
- memory: always;
- DuckDB stand-in: when duckdb is installed (same SQL text as PostgreSQL; semantics, not compatibility);
- PostgreSQL 18: only when DATAMESH_PG_DSN is set and psycopg 3 is installed.

``OpenAcceptanceCriteria`` lists criteria PR #43 does not meet yet. Each is an expected failure, so the
suite stays green while the gap is visible; when a gap closes, the unexpected success fails the run and
the marker must be removed. The PR is acceptance-ready only when that class is empty.
"""
import hashlib
import importlib.util
import io
import json
import logging
import os
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.application.ingest.reference_documents import ReferenceDocumentSelection, ReferenceIngestProfile
from app.infrastructure.ingest.reference_documents import (
    LoadedReferenceDocument, build_bundle, hydrate_bundle, ingest_and_hydrate, load_bundle, write_bundle,
)

T0 = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
HANDLE = "ref_acceptance_doc_001"
CANARY = "ZQX-PRIVATE-CANARY-7731"
PROFILE = ReferenceIngestProfile(
    profile_id="acceptance-profile", version="1",
    heading_pattern=r"(?P<key>\d+(?:\.\d+)*)\s+(?P<title>.+)",
)
SOURCE = (
    "Synthetic reference\r\n\r\n"
    "1 Scope\r\nOpening paragraph with Unicode: é ✓.\r\nSecond line, same passage.\r\n\r\n"
    "1.1 Boundary\r\n  Indented nested evidence.\r\n\r\n"
    "1.1.1 Deep clause\r\nDeepest statement.\r\n\r\n"
    "2 Requirements\r\nLast paragraph.\r\n"
)
# Cross-version determinism: Python 3.11 and 3.12 must produce this exact payload digest.
GOLDEN_PAYLOAD_SHA256 = "e5a3385c07be628a39504123b63ac6ac555848c210d2bb86c301eed326a07656"
HAS_DUCKDB = importlib.util.find_spec("duckdb") is not None
HAS_PYPDF = importlib.util.find_spec("pypdf") is not None
PG_DSN = os.environ.get("DATAMESH_PG_DSN")
HAS_PSYCOPG = importlib.util.find_spec("psycopg") is not None


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def synthetic_pdf(pages: list[str]) -> bytes:
    """Minimal valid PDF with one Helvetica text line per page. Deterministic, no external tools."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None,
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET"
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content} 0 R >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


class FailingPut:
    """Unit-of-work proxy that fails the nth object write, to prove all-or-nothing hydration."""

    def __init__(self, factory, fail_at):
        self.factory, self.fail_at = factory, fail_at

    def __call__(self):
        inner, fail_at = self.factory(), self.fail_at

        class Objects:
            def __init__(self, real):
                self.real, self.calls = real, 0

            def put(self, obj):
                self.calls += 1
                if self.calls == fail_at:
                    raise RuntimeError("injected_store_failure")
                return self.real.put(obj)

            def __getattr__(self, name):
                return getattr(self.real, name)

        class Proxy:
            def __enter__(self):
                self.uow = inner.__enter__()
                self.objects, self.commands = Objects(self.uow.objects), self.uow.commands
                return self

            def __exit__(self, *exc):
                return inner.__exit__(*exc)

            def commit(self):
                self.uow.commit()

        return Proxy()


class HydrationAcceptance:
    """Mixin: subclasses implement make() returning a unit-of-work factory."""

    def make(self):
        raise NotImplementedError

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.root.mkdir()
        self.uow = self.make()

    def source(self, name="source.txt", text=SOURCE):
        path = self.root / name
        path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        return name, sha(path.read_bytes())

    def run_pipeline(self, name="source.txt", text=SOURCE, handle=HANDLE, out="derived/source.json", at=T0):
        rel, digest = self.source(name, text)
        return ingest_and_hydrate(self.root, rel, handle, out, digest, PROFILE, self.uow, at)

    def stored(self, object_id):
        with self.uow() as uow:
            return uow.objects.get(object_id)

    def history(self, object_id):
        with self.uow() as uow:
            return uow.objects.history(object_id)

    # A1: every node lands exactly once, with exact source text and its parent edge.
    def test_graph_is_a_faithful_image_of_the_bundle(self):
        bundle, result = self.run_pipeline()
        self.assertFalse(result.replayed)
        self.assertEqual(result.object_ids, tuple(n.node_id for n in bundle.nodes))
        self.assertEqual(len(set(result.object_ids)), len(bundle.nodes))
        kinds = {"document": "reference_document", "section": "reference_section", "passage": "reference_passage"}
        for node in bundle.nodes:
            obj = self.stored(node.node_id)
            self.assertIsNotNone(obj, node.node_id)
            self.assertEqual(obj.kind, kinds[node.kind])
            if node.kind == "document":
                self.assertEqual(obj.relations, ())
                self.assertEqual(obj.text, "")
            else:
                page = bundle.pages[node.page_number - 1].text
                self.assertEqual(obj.text, page[node.start_offset:node.end_offset])
                self.assertEqual([(r.type, r.target_id) for r in obj.relations], [("part_of", node.parent_node_id)])
            self.assertEqual(obj.fields["payload_sha256"], bundle.payload_sha256)
            self.assertEqual(obj.fields["source_sha256"], bundle.source_sha256)
            self.assertEqual(obj.provenance.content_sha256, bundle.source_sha256)

    # A2: sections and passages cover every non-blank source character exactly once.
    def test_spans_cover_source_without_gaps_or_overlap(self):
        bundle, _ = self.run_pipeline()
        for page in bundle.pages:
            owners = [0] * len(page.text)
            for node in bundle.nodes:
                if node.kind != "document" and node.page_number == page.page_number:
                    for i in range(node.start_offset, node.end_offset):
                        owners[i] += 1
            for i, char in enumerate(page.text):
                if char.strip():
                    self.assertEqual(owners[i], 1, f"page {page.page_number} offset {i}")

    # A3: nesting follows heading numbering, fractaling inward.
    def test_hierarchy_nests_inward_by_heading_depth(self):
        bundle, _ = self.run_pipeline()
        by_id = {n.node_id: n for n in bundle.nodes}
        keys = {n.section_key: n for n in bundle.nodes if n.kind == "section"}
        self.assertEqual(list(keys), ["1", "1.1", "1.1.1", "2"])
        self.assertEqual(keys["1.1"].parent_node_id, keys["1"].node_id)
        self.assertEqual(keys["1.1.1"].parent_node_id, keys["1.1"].node_id)
        self.assertEqual(keys["2"].parent_node_id, HANDLE)
        self.assertEqual([keys[k].depth for k in ("1", "1.1", "1.1.1")], [1, 2, 3])
        deepest = [n for n in bundle.nodes if n.parent_node_id == keys["1.1.1"].node_id]
        self.assertEqual([n.kind for n in deepest], ["passage"])
        for node in bundle.nodes[1:]:
            self.assertEqual(node.depth, by_id[node.parent_node_id].depth + 1)

    # A4: replay of the same bundle writes nothing new, even at a later time.
    def test_replay_is_idempotent_and_writes_no_new_versions(self):
        bundle, first = self.run_pipeline()
        path = self.root / "derived/source.json"
        loaded = load_bundle(self.root, "derived/source.json", sha(path.read_bytes()), T0 + timedelta(days=1))
        again = hydrate_bundle(loaded, self.uow, T0 + timedelta(days=1))
        self.assertTrue(again.replayed)
        self.assertEqual(again.object_ids, first.object_ids)
        for object_id in first.object_ids:
            self.assertEqual(len(self.history(object_id)), 1)

    # A5: a failure mid-hydration leaves no objects and no command record.
    def test_failed_hydration_is_all_or_nothing(self):
        rel, digest = self.source()
        bundle = build_bundle(self.root, rel, HANDLE, digest, PROFILE)
        json_sha = write_bundle(self.root, "derived/source.json", bundle)
        loaded = load_bundle(self.root, "derived/source.json", json_sha, T0)
        with self.assertRaisesRegex(RuntimeError, "injected_store_failure"):
            hydrate_bundle(loaded, FailingPut(self.uow, fail_at=len(bundle.nodes)), T0)
        for node in bundle.nodes:
            self.assertIsNone(self.stored(node.node_id))
        with self.uow() as uow:
            self.assertIsNone(uow.commands.get("refdoc-" + bundle.payload_sha256[:48]))
        retry = hydrate_bundle(loaded, self.uow, T0)
        self.assertFalse(retry.replayed)
        self.assertEqual(len(retry.object_ids), len(bundle.nodes))

    # A6: a revised source keeps the earlier revision's evidence retrievable, never overwritten.
    def test_revision_is_additive_and_prior_evidence_survives(self):
        first, _ = self.run_pipeline(out="derived/r1.json")
        revised = SOURCE.replace("Last paragraph.", "Last paragraph, revised.")
        second, result = self.run_pipeline(text=revised, out="derived/r2.json", at=T0 + timedelta(hours=1))
        self.assertFalse(result.replayed)
        self.assertNotEqual(first.payload_sha256, second.payload_sha256)
        old_passage = [n for n in first.nodes if n.kind == "passage"][-1]
        survivor = self.stored(old_passage.node_id)
        self.assertEqual(survivor.text, "Last paragraph.")
        self.assertEqual(survivor.fields["payload_sha256"], first.payload_sha256)
        self.assertEqual(len(self.history(HANDLE)), 2)

    # A7: every hydrated object is a source-literal candidate, with no authority-bearing fields.
    def test_objects_carry_no_authority(self):
        bundle, result = self.run_pipeline()
        forbidden = {"approved", "approval", "accepted", "authority", "status", "decision"}
        for object_id in result.object_ids:
            obj = self.stored(object_id)
            self.assertEqual(obj.fields["epistemic_scope"], "source_literal_candidate")
            self.assertEqual(obj.provenance.platform, "private_ref")
            self.assertFalse(forbidden & set(obj.fields))
            self.assertEqual(obj.resources, ())


class MemoryHydrationAcceptance(HydrationAcceptance, unittest.TestCase):
    def make(self):
        from app.infrastructure.persistence import build_memory
        return build_memory()


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class DuckDbHydrationAcceptance(HydrationAcceptance, unittest.TestCase):
    def make(self):
        from app.infrastructure.persistence import build_duckdb_standin
        return build_duckdb_standin()


@unittest.skipUnless(PG_DSN and HAS_PSYCOPG, "set DATAMESH_PG_DSN and install psycopg 3 to run against PostgreSQL 18")
class PostgresHydrationAcceptance(HydrationAcceptance, unittest.TestCase):
    """Runs in a throwaway schema per test; drops it afterwards."""

    def make(self):
        import psycopg
        from app.infrastructure.persistence import POSTGRES, SqlUnitOfWorkFactory
        self.schema = "dm_refacc_" + uuid.uuid4().hex[:12]
        with psycopg.connect(PG_DSN, autocommit=True) as c:
            c.execute(f'CREATE SCHEMA "{self.schema}"')
        self.addCleanup(self._drop)

        def connect():
            c = psycopg.connect(PG_DSN, autocommit=True)
            c.execute(f'SET search_path TO "{self.schema}", public')
            return c

        factory = SqlUnitOfWorkFactory(connect, POSTGRES, close=lambda c: c.close())
        factory.migrate()
        return factory

    def _drop(self):
        import psycopg
        with psycopg.connect(PG_DSN, autocommit=True) as c:
            c.execute(f'DROP SCHEMA "{self.schema}" CASCADE')


class ExtractionAcceptance(unittest.TestCase):
    """Store-independent criteria: determinism, trust boundary, limits and privacy of failures."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.root.mkdir()

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return name, sha(path.read_bytes())

    # B1: identical inputs give byte-identical JSON on every supported Python.
    def test_bundle_is_deterministic_and_matches_golden_digest(self):
        rel, digest = self.write("source.txt", SOURCE)
        a = build_bundle(self.root, rel, HANDLE, digest, PROFILE)
        b = build_bundle(self.root, rel, HANDLE, digest, PROFILE)
        self.assertEqual(a.model_dump_json(), b.model_dump_json())
        self.assertEqual(write_bundle(self.root, "a.json", a), write_bundle(self.root, "b.json", b))
        self.assertEqual(a.payload_sha256, GOLDEN_PAYLOAD_SHA256)

    # B2: CRLF and Unicode offsets are exact codepoint spans.
    def test_offsets_are_exact_for_crlf_and_unicode(self):
        rel, digest = self.write("source.txt", SOURCE)
        bundle = build_bundle(self.root, rel, HANDLE, digest, PROFILE)
        page = bundle.pages[0].text
        self.assertEqual(page, SOURCE)
        unicode_passage = next(n for n in bundle.nodes if n.kind == "passage" and "é" in page[n.start_offset:n.end_offset])
        self.assertEqual(page[unicode_passage.start_offset:unicode_passage.end_offset],
                         "Opening paragraph with Unicode: é ✓.\r\nSecond line, same passage.")

    # B3: long bodies split into bounded passages without dropping a character.
    def test_long_body_chunks_are_bounded_and_lossless(self):
        line = "synthetic filler sentence for chunking.\n"
        body = "1 Long\n" + line * 1200
        rel, digest = self.write("long.txt", body)
        bundle = build_bundle(self.root, rel, HANDLE, digest, PROFILE)
        passages = [n for n in bundle.nodes if n.kind == "passage"]
        self.assertGreater(len(passages), 1)
        self.assertTrue(all(n.end_offset - n.start_offset <= PROFILE.max_chunk_chars for n in passages))
        page = bundle.pages[0].text
        self.assertEqual("".join(page[n.start_offset:n.end_offset] for n in passages), (line * 1200).rstrip("\n"))

    # B4: multi-page PDF sources keep page-scoped spans.
    @unittest.skipUnless(HAS_PYPDF, "install the pdf extra to run PDF acceptance")
    def test_pdf_pages_hydrate_with_page_scoped_spans(self):
        from app.infrastructure.persistence import build_memory
        rel, digest = self.write("source.pdf", synthetic_pdf(["1 First page heading", "Second page body text"]))
        store = build_memory()
        bundle, result = ingest_and_hydrate(self.root, rel, HANDLE, "derived/pdf.json", digest, PROFILE, store, T0)
        self.assertEqual(bundle.source_format, "pdf")
        self.assertEqual(len(bundle.pages), 2)
        self.assertEqual({n.page_number for n in bundle.nodes if n.kind != "document"}, {1, 2})
        self.assertEqual(len(result.object_ids), len(bundle.nodes))

    # B5: tampered, mismatched, oversize and escaping inputs fail closed before any write.
    def test_untrusted_inputs_fail_closed(self):
        rel, digest = self.write("source.txt", SOURCE)
        bundle = build_bundle(self.root, rel, HANDLE, digest, PROFILE)
        json_sha = write_bundle(self.root, "derived/source.json", bundle)
        cases = {
            "source hash": lambda: build_bundle(self.root, rel, HANDLE, "1" * 64, PROFILE),
            "json hash": lambda: load_bundle(self.root, "derived/source.json", "1" * 64, T0),
            "escape": lambda: build_bundle(self.root, "../outside.txt", HANDLE, digest, PROFILE),
            "oversize": lambda: build_bundle(self.root, rel, HANDLE, digest,
                                             PROFILE.model_copy(update={"max_file_bytes": 8})),
            "unsupported": lambda: build_bundle(self.root, self.write("x.exe", b"MZ")[0], HANDLE, sha(b"MZ"), PROFILE),
        }
        for label, call in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                call()
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("outside")
        (self.root / "link.txt").symlink_to(outside)
        with self.assertRaises(ValueError):
            build_bundle(self.root, "link.txt", HANDLE, sha(b"outside"), PROFILE)
        self.assertEqual(json_sha, sha((self.root / "derived/source.json").read_bytes()))

    # B6: a forged loader receipt for a different bundle is rejected before writing.
    def test_mismatched_receipt_is_rejected(self):
        from app.infrastructure.persistence import build_memory
        rel, digest = self.write("source.txt", SOURCE)
        bundle = build_bundle(self.root, rel, HANDLE, digest, PROFILE)
        forged = ReferenceDocumentSelection(document_id=HANDLE, source_sha256="2" * 64, payload_sha256=bundle.payload_sha256,
                                            json_file_sha256="3" * 64, selected_at=T0)
        store = build_memory()
        with self.assertRaisesRegex(ValueError, "selection does not match"):
            hydrate_bundle(LoadedReferenceDocument(bundle, forged), store, T0)
        with store() as uow:
            self.assertIsNone(uow.objects.get(HANDLE))

    # B7: failures never echo private source text in messages, causes or logs.
    def test_failures_do_not_leak_source_text(self):
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        long_heading = "1 " + CANARY + "x" * 600
        rel, digest = self.write("leak.txt", "Intro " + CANARY + "\n\n" + long_heading + "\n")
        good_rel, good_digest = self.write(CANARY + ".txt", "Intro " + CANARY + "\n")
        bundle = build_bundle(self.root, good_rel, HANDLE, good_digest, PROFILE)
        write_bundle(self.root, "derived/good.json", bundle)
        tampered = json.loads((self.root / "derived/good.json").read_text())
        tampered["nodes"][1]["end_offset"] = 10_000
        name, tampered_sha = self.write("derived/tampered.json", json.dumps(tampered))
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            for label, call in {
                "heading": lambda: build_bundle(self.root, rel, HANDLE, digest, PROFILE),
                "hash": lambda: build_bundle(self.root, rel, HANDLE, "4" * 64, PROFILE),
                "tampered": lambda: load_bundle(self.root, name, tampered_sha, T0),
            }.items():
                with self.subTest(label):
                    try:
                        call()
                    except Exception as error:  # noqa: BLE001 - inspect the whole chain
                        chain, current = [], error
                        while current is not None:
                            chain.append(str(current))
                            current = current.__cause__ or current.__context__
                        self.assertNotIn(CANARY, "\n".join(chain))
                    else:
                        self.fail("untrusted input accepted")
        self.assertNotIn(CANARY, stderr.getvalue() + "\n".join(records))


class OpenAcceptanceCriteria(unittest.TestCase):
    """Criteria PR #43 does not meet yet. Remove each marker in the change that closes it."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.root.mkdir()
        from app.infrastructure.persistence import build_memory
        self.store = build_memory()

    def hydrate(self, text, out, at=T0, name="source.txt"):
        path = self.root / name
        path.write_bytes(text.encode() if isinstance(text, str) else text)
        return ingest_and_hydrate(self.root, name, HANDLE, out, sha(path.read_bytes()), PROFILE, self.store, at)

    @unittest.expectedFailure
    def test_gap_edges_pin_both_endpoint_versions(self):
        """Contract: every edge pins source AND target versions. Today only the source version is recorded."""
        bundle, _ = self.hydrate(SOURCE, "derived/a.json")
        with self.store() as uow:
            child = uow.objects.get(bundle.nodes[1].node_id)
        relation = child.relations[0].model_dump()
        self.assertIn("target_version", relation)

    @unittest.expectedFailure
    def test_gap_superseded_revision_leaves_current_graph(self):
        """A new revision under the same handle must retire the prior revision's nodes from the current view."""
        self.hydrate(SOURCE, "derived/r1.json")
        second, _ = self.hydrate(SOURCE.replace("Last paragraph.", "Revised."), "derived/r2.json", at=T0 + timedelta(hours=1))
        current = {n.node_id for n in second.nodes if n.kind == "section"}
        with self.store() as uow:
            listed = {o.object_id for o in uow.objects.by_kind("reference_section")}
        self.assertEqual(listed, current)

    @unittest.expectedFailure
    def test_gap_hydration_requires_loader_verified_receipt(self):
        """A self-consistent receipt built in memory, never read from disk, must not be hydrated."""
        path = self.root / "source.txt"
        path.write_text(SOURCE)
        bundle = build_bundle(self.root, "source.txt", HANDLE, sha(path.read_bytes()), PROFILE)
        forged = ReferenceDocumentSelection(document_id=bundle.document_id, source_sha256=bundle.source_sha256,
                                            payload_sha256=bundle.payload_sha256, json_file_sha256="5" * 64, selected_at=T0)
        with self.assertRaises(ValueError):
            hydrate_bundle(LoadedReferenceDocument(bundle, forged), self.store, T0)

    @unittest.expectedFailure
    def test_gap_partial_coverage_is_recorded(self):
        """Preview sources must carry explicit coverage status (full / partial) into JSON and the graph."""
        bundle, _ = self.hydrate(SOURCE, "derived/a.json")
        self.assertIn("coverage", bundle.model_dump())

    @unittest.expectedFailure
    def test_gap_ontology_sources_are_supported(self):
        """OWL/RDF-XML reference sources must ingest under the same JSON and hydration contract."""
        owl = '<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>'
        self.hydrate(owl, "derived/o.json", name="source.owl")

    @unittest.expectedFailure
    def test_gap_long_private_locator_hydrates(self):
        """Bundle schema allows 1024-character locators, but the root node title caps at 500, so a valid locator fails."""
        name = "/".join(["n" * 120] * 5) + "/source.txt"
        (self.root / name).parent.mkdir(parents=True)
        self.assertGreater(len(name), 500)
        self.hydrate(SOURCE, "derived/long.json", name=name)


if __name__ == "__main__":
    unittest.main()
