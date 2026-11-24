"""Synthetic offline checks only; no private graph or live database access."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "check_graph_sources", Path(__file__).resolve().parents[1] / "scripts/check_graph_sources.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class GraphSourceCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = "Synthetic source café.\n".encode()
        self.profile = dict(profile_id="synthetic-tree", version="1", heading_pattern=None,
                            max_file_bytes=33554432, max_pages=2000,
                            max_extracted_chars=20000000, max_chunk_chars=18000,
                            coverage="unknown", coverage_reason=None)
        did = "ref_synthetic_document_v1"
        pid = "ref_synthetic_passage_v1"
        self.bundle = dict(schema_version="currentcraft-ref-document/v1", document_id=did,
                           source_name="synthetic.md", source_format="markdown", coverage="unknown",
                           coverage_reason=None, source_sha256=sha(self.source),
                           extractor_name="utf8", extractor_version="stdlib-1",
                           profile_sha256=sha(canonical(self.profile)),
                           pages=[dict(page_number=1, text=self.source.decode())], nodes=[
                               dict(node_id=did, kind="document", parent_node_id=None, ordinal=1,
                                    depth=0, page_number=None, start_offset=None, end_offset=None,
                                    section_key=None, title="synthetic.md", section_level=None),
                               dict(node_id=pid, kind="passage", parent_node_id=did, ordinal=2,
                                    depth=1, page_number=1, start_offset=0,
                                    end_offset=len(self.source.decode())-1, section_key=None,
                                    title="Passage", section_level=None)])
        self.bundle["payload_sha256"] = sha(canonical(self.bundle))
        self.graph = dict(schema_version="currentcraft-ref-graph-export/v1",
                          snapshot_id="synthetic-snapshot-1", documents=[did], nodes=[], edges=[])
        # Independent expected export construction, not checker.expected_document.
        for node, kind, text in [(self.bundle["nodes"][0], "reference_document", ""),
                                  (self.bundle["nodes"][1], "reference_passage", self.source.decode()[:-1])]:
            fields = dict(schema_version="currentcraft-ref-document/v1", node_kind=node["kind"],
                          source_sha256=sha(self.source), payload_sha256=self.bundle["payload_sha256"],
                          profile_sha256=self.bundle["profile_sha256"], extractor_name="utf8",
                          extractor_version="stdlib-1", depth=node["depth"], ordinal=node["ordinal"],
                          page_number=node["page_number"], start_offset=node["start_offset"],
                          end_offset=node["end_offset"], section_key=None, section_level=None,
                          source_name="synthetic.md" if node["kind"] == "document" else None,
                          epistemic_scope="source_literal_candidate", coverage="unknown",
                          coverage_reason=None)
            self.graph["nodes"].append(dict(object_id=node["node_id"], version_no=3, kind=kind,
                                           title=node["title"], text=text, fields=fields,
                                           provenance=dict(source_id=did, content_sha256=sha(self.source),
                                                           adapter="ref_document_tree", adapter_version="1.0")))
        self.graph["edges"] = [dict(src_id=pid, rel_type="part_of", dst_id=did, src_version=3,
                                    dst_version=3, evidence="reference_tree.parent_node_id")]
        self.refresh()

    def write(self, name, raw):
        (self.root / name).write_bytes(raw)
        return dict(path=name, sha256=sha(raw))

    def refresh(self):
        self.manifest = dict(schema_version="currentcraft-graph-check/v1", graph={
            **self.write("graph.json", canonical(self.graph)), "snapshot_id": "synthetic-snapshot-1"},
            documents=[dict(document_id="ref_synthetic_document_v1",
                            source=self.write("source.md", self.source),
                            profile=self.write("profile.json", canonical(self.profile)),
                            bundle=self.write("bundle.json", canonical(self.bundle)))])
        self.manifest_hash = self.write("manifest.json", canonical(self.manifest))["sha256"]

    def run_cli(self, **kwargs):
        opts = dict(root=str(self.root), manifest="manifest.json", manifest_sha256=self.manifest_hash)
        opts.update(kwargs)
        args = [item for k,v in opts.items() for item in ("--"+k.replace("_", "-"), v)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = checker.main(args)
        return code, output.getvalue()

    def fails(self, code=None):
        exit_code, text = self.run_cli()
        self.assertEqual(exit_code, 1)
        result = json.loads(text)
        self.assertEqual(result["status"], "fail")
        if code:
            self.assertEqual(result["code"], code)
        for private in (str(self.root), "synthetic.md", "ref_synthetic", "café"):
            self.assertNotIn(private, text)

    def test_match_and_read_only(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), dict(status="match", code="selected_snapshot_matches_pins",
                                               documents=1, nodes=2, edges=1))
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_independent_manifest_pin(self):
        code, out = self.run_cli(manifest_sha256="0"*64)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["code"], "file_hash_mismatch")

    def test_changed_source_bytes(self):
        (self.root/"source.md").write_bytes(b"changed")
        self.fails("file_hash_mismatch")

    def test_changed_bundle_bytes(self):
        (self.root/"bundle.json").write_bytes(b"{}")
        self.fails("file_hash_mismatch")

    def test_repin_source_without_bundle(self):
        self.source += b"changed"
        self.refresh()
        self.fails("source_hash_mismatch")

    def test_profile_hash_drift(self):
        self.profile["version"] = "2"
        self.refresh()
        self.fails("profile_hash_mismatch")

    def test_payload_digest_tamper(self):
        self.bundle["payload_sha256"] = "0"*64
        self.refresh()
        self.fails("payload_hash_mismatch")

    def test_literal_and_metadata_drift(self):
        original = copy.deepcopy(self.graph)
        for key, value in [("title","changed"),("text","changed"),("kind","reference_section")]:
            with self.subTest(key=key):
                self.graph=copy.deepcopy(original)
                self.graph["nodes"][1][key]=value
                self.refresh()
                self.fails("node_content_mismatch")
        self.graph=copy.deepcopy(original)
        self.graph["nodes"][1]["fields"]["coverage"]="full"
        self.refresh()
        self.fails("node_content_mismatch")

    def test_bool_does_not_equal_integer(self):
        self.graph["nodes"][1]["fields"]["depth"]=True
        self.refresh()
        self.fails("node_content_mismatch")

    def test_provenance_drift(self):
        self.graph["nodes"][1]["provenance"]["content_sha256"]="0"*64
        self.refresh()
        self.fails("node_content_mismatch")

    def test_edge_versions_and_legacy_unpinned(self):
        for field,value in [("src_version",4),("dst_version",4),("dst_version",None),("src_version",True)]:
            with self.subTest(field=field,value=value):
                self.graph["edges"][0].update(src_version=3,dst_version=3)
                self.graph["edges"][0][field]=value
                self.refresh()
                self.fails("edge_version_mismatch")

    def test_wrong_parent(self):
        self.graph["edges"][0]["dst_id"]="ref_other"
        self.refresh()
        self.fails("edge_set_mismatch")

    def test_missing_extra_duplicate_nodes(self):
        original=copy.deepcopy(self.graph)
        variants=[original["nodes"][:-1],original["nodes"]+[original["nodes"][1]],
                  [original["nodes"][0],original["nodes"][0]]]
        for nodes in variants:
            with self.subTest(count=len(nodes)):
                self.graph=copy.deepcopy(original)
                self.graph["nodes"]=nodes
                self.refresh()
                self.fails("node_set_mismatch")

    def test_missing_extra_edges(self):
        edge=copy.deepcopy(self.graph["edges"][0])
        for edges in [[],[edge,edge]]:
            self.graph["edges"]=edges
            self.refresh()
            self.fails("edge_set_mismatch")

    def test_selection_and_snapshot_mismatch(self):
        self.graph["documents"]=["ref_other"]
        self.refresh()
        self.fails("selection_mismatch")
        self.graph["documents"]=["ref_synthetic_document_v1"]
        self.graph["snapshot_id"]="other"
        self.refresh()
        self.fails("snapshot_mismatch")

    def test_closed_and_unsupported_export(self):
        self.graph["extra"]="not allowed"
        self.refresh()
        self.fails("invalid_shape")
        del self.graph["extra"]
        self.graph["schema_version"]="unsupported"
        self.refresh()
        self.fails("unsupported_export")

    def test_unsafe_paths(self):
        for path in ["../secret", "/absolute", "nested/../secret", "nested\\secret"]:
            with self.subTest(path=path):
                code,out=self.run_cli(manifest=path)
                self.assertEqual(code,1)
                self.assertEqual(json.loads(out)["code"],"unsafe_path")

    def test_symlink_file_and_directory(self):
        (self.root/"link.json").symlink_to(self.root/"manifest.json")
        code,out=self.run_cli(manifest="link.json")
        self.assertEqual(code,1)
        self.assertNotIn(str(self.root),out)
        (self.root/"linked").symlink_to(self.root, target_is_directory=True)
        code,_=self.run_cli(manifest="linked/manifest.json")
        self.assertEqual(code,1)

    def test_duplicate_json_and_nonfinite(self):
        for raw in [b'{"schema_version":1,"schema_version":2}', b'{"value":NaN}']:
            self.manifest_hash=self.write("manifest.json",raw)["sha256"]
            self.fails()

    def test_invalid_input_does_not_echo_values(self):
        for raw in [b'not-json',b'\xff',b'[]']:
            self.manifest_hash=self.write("manifest.json",raw)["sha256"]
            self.fails()
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(checker.main(["--private-value-that-must-not-echo"]),1)
        self.assertNotIn("private-value",out.getvalue())

    def test_bounded_reads(self):
        with patch.object(checker,"MAX_BYTES",1):
            self.fails("file_limit")


if __name__ == "__main__":
    unittest.main()
