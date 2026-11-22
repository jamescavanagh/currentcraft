import ast
import importlib.util
from pathlib import Path
import unittest

from pydantic import ValidationError
from tests.test_six_domain_types import fixture, fact, rebuild
from app.application.feature_graph.domain_types import validate_six_type_packet
from app.application.feature_graph.references import CONTRACTS as RESOLUTION_CONTRACTS
from app.domain.operand.types import CONTRACTS, context_kind

ROOT = Path(__file__).resolve().parent.parent


class SixDomainBoundaryTests(unittest.TestCase):
    def test_determinate_sat_requires_observed_conditions(self):
        packet = fixture()
        for conditions in ({"value": None, "epistemic_status": "unknown", "missing_reason": "not supplied"},
                           fact("synthetic conditions", "inferred")):
            with self.assertRaises(ValidationError):
                rebuild(packet.test, conditions=conditions)

    def test_cross_extension_identity_collision_is_rejected(self):
        packet = fixture()
        order = rebuild(packet.order, extension_id=packet.project.extension_id)
        with self.assertRaisesRegex(ValueError, "packet_identity_collision"):
            validate_six_type_packet(rebuild(packet, order=order))

    def test_extension_cannot_reuse_another_canonical_identity(self):
        packet = fixture()
        order = rebuild(packet.order, extension_id=packet.document.document.identity)
        with self.assertRaisesRegex(ValueError, "packet_identity_collision"):
            validate_six_type_packet(rebuild(packet, order=order))

    def test_context_kinds_match_existing_six_domain_profiles(self):
        from app.domain.operand.profile import CONTEXT_KINDS
        self.assertEqual(tuple(context_kind(e) for e in fixture().extensions()), tuple(CONTEXT_KINDS.values()))

    def test_new_fields_have_descriptions(self):
        for model in CONTRACTS + RESOLUTION_CONTRACTS:
            for name in model.__annotations__:
                if name in model.model_fields:
                    self.assertTrue(model.model_fields[name].description, (model.__name__, name))

    def test_generated_reference_is_current(self):
        spec = importlib.util.spec_from_file_location("six_type_docs", ROOT / "scripts/gen_six_type_docs.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        self.assertEqual(generator.OUT.read_text(), generator.render())
        defs = generator.schema()["$defs"]
        for name in ("SixTypePacket", "ResolutionReport", "OwnershipProfile", "CanonicalRef"):
            self.assertIn(name, defs)

    def test_no_heavy_imports_or_layer_inversion(self):
        heavy = {"numpy", "scipy", "torch", "pandas", "fastapi", "starlette", "uvicorn"}
        for relative, forbidden in (("src/app/domain/operand/types.py", ("app.application", "app.infrastructure", "app.interfaces")),
                                    ("src/app/application/feature_graph/domain_types.py", ("app.infrastructure", "app.interfaces")),
                                    ("src/app/application/feature_graph/references.py", ("app.infrastructure", "app.interfaces")),
                                    ("src/app/infrastructure/feature_graph/canonical.py", ("app.interfaces",)),
                                    ("src/app/infrastructure/feature_graph/ownership.py", ("app.interfaces",))):
            path = ROOT / relative
            names = []
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names.append(node.module)
            self.assertFalse([n for n in names if n.startswith(forbidden) or n.split(".")[0] in heavy], relative)

    def test_domain_extensions_do_not_import_canonical_entity_classes(self):
        tree = ast.parse((ROOT / "src/app/domain/operand/types.py").read_text())
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        for canonical in ("app.domain.project.project_entity", "app.domain.document.document",
                          "app.domain.commercial.commercial_order", "app.domain.project.subsystem"):
            self.assertNotIn(canonical, modules)

    def test_receipt_contains_no_source_text_or_operational_grant(self):
        receipt = validate_six_type_packet(fixture())
        text = receipt.model_dump_json()
        for value in ("synthetic scope", "synthetic boundary", "synthetic conditions"):
            self.assertNotIn(value, text)
        self.assertFalse(receipt.grants_authority)
        self.assertNotIn("acceptance_decision", receipt.model_dump())

    def test_positive_extension_and_graph_revisions_are_strict(self):
        packet = fixture()
        for value in (True, 0, "2"):
            with self.assertRaises(ValidationError):
                rebuild(packet.document, extension_version=value)
            with self.assertRaises(ValidationError):
                rebuild(packet.configuration, graph_revision=value)

    def test_cross_record_binding_detects_selection_digest_change(self):
        packet = fixture()
        binding = rebuild(packet.configuration.binding(), selection_digest="f" * 64)
        document = rebuild(packet.document, configuration=fact(binding))
        with self.assertRaisesRegex(ValueError, "document_configuration_mismatch"):
            validate_six_type_packet(rebuild(packet, document=document))


if __name__ == "__main__":
    unittest.main()
