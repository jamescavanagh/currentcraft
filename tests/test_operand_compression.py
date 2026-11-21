"""Six-domain reference acceptance; numerical compression is a separate consumer."""
import unittest
from uuid import UUID
from pydantic import ValidationError
from app.domain.operand import ConfigurationLink, OperandProfile, OperandRef
from app.domain.operand.profile import CONTEXT_KINDS, CONTEXT_LINKS


class SixDomainReferenceTests(unittest.TestCase):
    def profile(self, context="projects"):
        return OperandProfile(profile_id=UUID(int=1), projection_ref=UUID(int=2),
            operand=OperandRef(object_id=UUID(int=3), record_version=7, object_kind=CONTEXT_KINDS[context], domain_context=context),
            configuration_link=ConfigurationLink(configuration_id=UUID(int=4), graph_id=UUID(int=5), graph_revision=2,
                predicate=CONTEXT_LINKS[context], evidence_ids=(UUID(int=6),)))

    def test_all_six_contexts_and_typed_links(self):
        self.assertEqual(len(CONTEXT_KINDS), 6)
        for context in CONTEXT_KINDS:
            with self.subTest(context=context):
                profile = self.profile(context)
                self.assertEqual(profile.operand.domain_context, context)
                self.assertEqual(profile.operand.object_id, UUID(int=3))
                self.assertEqual(profile.operand.record_version, 7)

    def test_old_contexts_and_people_rejected(self):
        for context in ("inventory", "employees_contributors", "drawings", "clients", "product_features", "timecards"):
            with self.subTest(context=context), self.assertRaises(ValidationError):
                OperandRef(object_id=UUID(int=3), record_version=1, object_kind="project", domain_context=context)
        for kind in ("person", "employee", "resource", "client", "agent", "team"):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                OperandRef(object_id=UUID(int=3), record_version=1, object_kind=kind, domain_context="projects")

    def test_context_kind_mismatch_rejected(self):
        with self.assertRaises(ValidationError):
            OperandRef(object_id=UUID(int=3), record_version=1, object_kind="order", domain_context="projects")

    def test_link_predicate_must_match_context(self):
        data = self.profile().model_dump()
        data["configuration_link"]["predicate"] = "requests_configuration"
        with self.assertRaises(ValidationError):
            OperandProfile(**data)

    def test_link_requires_unique_evidence(self):
        for ids in ((), (UUID(int=6), UUID(int=6))):
            data = self.profile().configuration_link.model_dump() | {"evidence_ids": ids}
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                ConfigurationLink(**data)

    def test_missing_link_asserts_no_configuration_fact(self):
        data = self.profile().model_dump() | {"configuration_link": None}
        self.assertIsNone(OperandProfile(**data).configuration_link)

    def test_old_soil_payloads_and_approval_rejected(self):
        for field, value in (("layers", ()), ("formation_sets", ()), ("interpretation_status", "approved")):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                OperandProfile(**(self.profile().model_dump() | {field: value}))

    def test_round_trip_preserves_existing_ids(self):
        profile = self.profile()
        restored = OperandProfile.model_validate_json(profile.model_dump_json())
        self.assertEqual(restored, profile)
        self.assertEqual(restored.operand.object_id, UUID(int=3))


if __name__ == "__main__":
    unittest.main()
