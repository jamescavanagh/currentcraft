"""Synthetic RDF/XML security regressions. No live network or private source data."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.application.ingest.reference_documents import ReferenceIngestProfile
from app.infrastructure.ingest import reference_documents as ref

OPEN = '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
CLOSE = "</rdf:RDF>"
CANARY = "SYNTHETIC_PRIVATE_CONTENT_7419"


class StreamingRdfSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "private"
        self.root.mkdir()
        self.profile = ReferenceIngestProfile(profile_id="synthetic-rdf-security", version="1")

    def build(self, text, profile=None, suffix=".owl"):
        raw = text.encode("utf-8")
        name = "source" + suffix
        (self.root / name).write_bytes(raw)
        return ref.build_bundle(self.root, name, "ref_synthetic_rdf_security",
                                hashlib.sha256(raw).hexdigest(), profile or self.profile)

    def reject(self, text, message):
        with self.assertRaisesRegex(ValueError, message) as caught:
            self.build(text)
        error = caught.exception
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertNotIn(CANARY, str(error))

    def test_depth_limit_includes_root_and_accepts_exact_boundary(self):
        accepted = OPEN + "<n>" * (ref.RDF_MAX_DEPTH - 1) + "</n>" * (ref.RDF_MAX_DEPTH - 1) + CLOSE
        self.assertEqual(self.build(accepted).pages[0].text, accepted)
        self.reject(OPEN + "<n>" * ref.RDF_MAX_DEPTH + "</n>" * ref.RDF_MAX_DEPTH + CLOSE, "depth limit")

    def test_element_limit_includes_root_and_accepts_exact_boundary(self):
        self.build(OPEN + "<n/>" * (ref.RDF_MAX_ELEMENTS - 1) + CLOSE)
        self.reject(OPEN + "<n/>" * ref.RDF_MAX_ELEMENTS + CLOSE, "element limit")

    def test_prior_wide_and_deep_review_probes_are_rejected(self):
        self.reject(OPEN + "<n/>" * 400_000 + CLOSE, "element limit")
        self.reject(OPEN + "<n>" * 60_000 + "</n>" * 60_000 + CLOSE, "depth limit")

    def test_attribute_count_and_value_limits(self):
        attrs = " ".join(f'a{i}="v"' for i in range(ref.RDF_MAX_ATTRIBUTES))
        self.build(OPEN + "<n " + attrs + "/>" + CLOSE)
        self.reject(OPEN + '<n ' + attrs + ' extra="v"/>' + CLOSE, "attribute limit")
        self.build(OPEN + '<n a="' + "a" * ref.RDF_MAX_ATTRIBUTE_CHARS + '"/>' + CLOSE)
        self.reject(OPEN + '<n a="' + "a" * (ref.RDF_MAX_ATTRIBUTE_CHARS + 1) + '"/>' + CLOSE,
                    "attribute value limit")

    def test_namespace_declarations_count_as_attributes_and_limit_uri_length(self):
        attrs = " ".join(f'xmlns:p{i}="urn:synthetic:{i}"' for i in range(ref.RDF_MAX_ATTRIBUTES))
        self.build(OPEN + "<n " + attrs + "/>" + CLOSE)
        self.reject(OPEN + '<n ' + attrs + ' extra="v"/>' + CLOSE, "attribute limit")
        self.reject(OPEN + '<n ' + attrs + ' xmlns:extra="urn:synthetic:extra"/>' + CLOSE, "attribute limit")
        self.reject(OPEN + '<n xmlns:x="' + "a" * (ref.RDF_MAX_ATTRIBUTE_CHARS + 1) + '"/>' + CLOSE,
                    "attribute value limit")

    def test_character_and_page_limits_precede_parser_creation(self):
        small = self.profile.model_copy(update={"max_extracted_chars": 128})
        for text, profile in ((OPEN + "<n/>" * 1000 + CLOSE, small),
                              (OPEN + " " * 2_000_000 + CLOSE, self.profile)):
            with self.subTest(limit=profile.max_extracted_chars), \
                 patch.object(ref.expat, "ParserCreate", side_effect=AssertionError("parser created too early")):
                with self.assertRaisesRegex(ValueError, "character limit|page exceeds"):
                    self.build(text, profile)

    def test_file_byte_limit_precedes_parser_creation(self):
        small = self.profile.model_copy(update={"max_file_bytes": 128})
        with patch.object(ref.expat, "ParserCreate", side_effect=AssertionError("parser created too early")):
            with self.assertRaisesRegex(ValueError, "byte limit"):
                self.build(OPEN + " " * 1000 + CLOSE, small)

    def test_structural_dtd_and_entity_rejection(self):
        documents = (
            '<!DOCTYPE rdf:RDF>' + OPEN + CLOSE,
            '<!DOCTYPE rdf:RDF SYSTEM "http://example.invalid/synthetic.dtd">' + OPEN + CLOSE,
            '<!DOCTYPE rdf:RDF [<!ENTITY x SYSTEM "file:///synthetic-secret">]>' + OPEN + "&x;" + CLOSE,
            '<!DOCTYPE rdf:RDF [<!ENTITY % x SYSTEM "http://example.invalid/x">%x;]>' + OPEN + CLOSE,
            '<!DOCTYPE rdf:RDF [<!ENTITY a "x"><!ENTITY b "&a;&a;&a;">]>' + OPEN + "&b;" + CLOSE,
        )
        for text in documents:
            with self.subTest(text=text):
                self.reject(text, "declarations")

    def test_comments_and_cdata_are_not_false_declarations(self):
        for literal in ("<!-- <!DOCTYPE harmless> -->", "<![CDATA[<!ENTITY harmless>]]>"):
            source = OPEN + literal + CLOSE
            self.assertEqual(self.build(source).pages[0].text, source)

    def test_imports_xinclude_stylesheets_and_schema_locations_stay_inert(self):
        source = ('<?xml-stylesheet href="http://example.invalid/synthetic.xsl"?>'
                  '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                  'xmlns:owl="http://www.w3.org/2002/07/owl#" '
                  'xmlns:xi="http://www.w3.org/2001/XInclude" '
                  'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                  'xsi:schemaLocation="urn:synthetic http://example.invalid/synthetic.xsd">'
                  '<owl:imports rdf:resource="http://example.invalid/synthetic.owl"/>'
                  '<xi:include href="file:///synthetic-secret" parse="text"/>' + CLOSE)
        with patch("socket.create_connection", side_effect=AssertionError("unexpected network")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("unexpected fetch")):
            self.assertEqual(self.build(source).pages[0].text, source)

    def test_wrong_root_malformed_undefined_entities_and_invalid_unicode_fail_safely(self):
        for source in ("<wrong/>", OPEN + CANARY + "<" + CLOSE, OPEN + "&missing;" + CLOSE,
                       OPEN + "\0" + CLOSE):
            self.reject(source, "ontology")

    def test_streaming_feed_is_bounded_and_stops_at_first_limit(self):
        real_create = ref.expat.ParserCreate
        calls = []
        modes = []
        class Recorder:
            def __init__(self, parser):
                object.__setattr__(self, "parser", parser)
            def __setattr__(self, name, value):
                setattr(self.parser, name, value)
            def __getattr__(self, name):
                return getattr(self.parser, name)
            def Parse(self, data, final):
                calls.append((len(data), final))
                return self.parser.Parse(data, final)
            def SetParamEntityParsing(self, mode):
                modes.append(mode)
                return self.parser.SetParamEntityParsing(mode)
        def create(*args, **kwargs):
            self.assertEqual(kwargs["namespace_separator"], "}")
            return Recorder(real_create(*args, **kwargs))
        with patch.object(ref.expat, "ParserCreate", side_effect=create):
            self.build(OPEN + "<n/>" * 10_000 + CLOSE)
            self.assertGreater(len(calls), 2)
            self.assertLessEqual(max(size for size, _ in calls), ref.RDF_CHUNK_CHARS)
            self.assertEqual(calls[-1], (0, True))
            self.assertEqual(modes, [ref.expat.XML_PARAM_ENTITY_PARSING_NEVER])
            calls.clear()
            self.reject(OPEN + "<n>" * 60_000 + "</n>" * 60_000 + CLOSE, "depth limit")
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0][1])

    def test_owl_policy_provenance_literal_offsets_and_id_stability(self):
        source = OPEN + "<n>synthetic é</n>" + CLOSE
        for suffix in (".owl", ".rdf"):
            bundle = self.build(source, suffix=suffix)
            self.assertEqual(bundle.extractor_version, "rdfxml-stream/1")
            self.assertEqual(bundle.pages[0].text, source)
            for node in bundle.nodes[1:]:
                material = (f"{bundle.document_id}|{bundle.source_sha256}|{node.kind}|{node.page_number}|"
                            f"{node.start_offset}|{node.end_offset}|{node.ordinal}").encode()
                self.assertEqual(node.node_id, "ref_" + hashlib.sha256(material).hexdigest()[:32])
                if node.kind == "passage":
                    self.assertEqual(source[node.start_offset:node.end_offset], source)

    def test_non_owl_does_not_parse_xml(self):
        source = "Synthetic literal <!DOCTYPE not-an-xml-document>"
        with patch.object(ref.expat, "ParserCreate", side_effect=AssertionError("non-OWL parsed as XML")):
            self.assertEqual(self.build(source, suffix=".txt").extractor_version, "stdlib-1")


if __name__ == "__main__":
    unittest.main()
