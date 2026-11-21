"""Synthetic six-type contracts and cross-record consistency, no dependency stubs."""
from datetime import datetime, timezone
from decimal import Decimal
import unittest
from uuid import UUID

from pydantic import ValidationError
from app.domain.commercial.commercial_order import Order
from app.domain.document.document import Document
from app.domain.project.project_entity import Project
from app.domain.project.subsystem import Subsystem
from app.domain.shared.quantities import Quantity, UnitRef
from app.domain.shared.versioning import VersionRef
from app.domain.operand.feature_graph import FeatureDefinition, FeatureGraphRevision, Provenance
from app.domain.operand.types import (DOMAIN_TYPES, CommercialOrderType, ConfigurationBinding,
    FeatureConfigurationType, FeatureRealization, OrderLine, ProjectType, RevisionAuthorization,
    SiteAcceptanceTestType, SubsystemInterface, SubsystemType, TestCriterion, WorkingDocumentType, record_ref)
from app.application.feature_graph.domain_types import SixTypePacket, validate_six_type_packet


def uid(number):
    return UUID(int=number)


def ref(number, version=1):
    return VersionRef(identity=uid(number), version=version)


def fact(value, status="observed"):
    return {"value": value, "epistemic_status": status, "evidence_ids": (uid(900),)}


def rebuild(model, **changes):
    return type(model)(**(model.model_dump() | changes))


def fixture():
    moment = datetime(2020, 1, 1, tzinfo=timezone.utc)
    provenance = Provenance(evidence_id=uid(900), source_snapshot_id=uid(901), captured_at=moment, method="human_label")
    feature = FeatureDefinition(feature_id=uid(1), version=1, definition_digest="1" * 64,
        status="active", mandatory=True, provenance=provenance)
    graph = FeatureGraphRevision(graph_id=uid(10), revision=1, valid_from=moment, recorded_at=moment, features=(feature,))
    config = FeatureConfigurationType(entity_id=uid(106), record_version=3, project=ref(100, 2),
        graph_id=graph.graph_id, graph_revision=graph.revision, graph_digest=graph.digest(), selected=(uid(1),))
    binding = config.binding()
    project = ProjectType(entity_id=uid(100), record_version=2, scope=fact("synthetic scope"),
        configuration_baseline=fact(binding), work_packages=(ref(700),))
    document = WorkingDocumentType(entity_id=uid(102), project_id=uid(100), project_revision=2,
        captured_revision=ref(202, 7), configuration=fact(binding))
    unit = UnitRef(dictionary_id="synthetic", dictionary_version="1", code="unit", dimension="count")
    line = OrderLine(line=ref(403), quantity=fact(Quantity(amount="2", unit=unit)), requested_configuration=fact(binding))
    order = CommercialOrderType(entity_id=uid(103), project_id=uid(100), project_revision=2,
        requested_configuration=fact(binding), lines=(line,))
    interface = SubsystemInterface(interface_id=uid(500), local_component=ref(404), peer=ref(405), specification=ref(406), evidence=(ref(900),))
    realization = FeatureRealization(feature_id=uid(1), component=ref(404), evidence=(ref(900),))
    subsystem = SubsystemType(entity_id=uid(104), project_id=uid(100), project_revision=2,
        boundary=fact("synthetic boundary"), configuration=fact(binding), components=(ref(404),),
        interfaces=(interface,), realizations=(realization,))
    criterion = TestCriterion(criterion=ref(800), expected=fact("ready"), observed=fact("ready"), result="pass", evidence=(ref(900),))
    test = SiteAcceptanceTestType(entity_id=uid(105), project=ref(100, 2), configuration=binding,
        basis=(document.captured_revision,), conditions=fact("synthetic conditions"), criteria=(criterion,),
        observed_configuration=fact(binding), result=fact("pass"), tested_at=fact(moment))
    return SixTypePacket(project=project, document=document, order=order, subsystem=subsystem,
        test=test, configuration=config, graph=graph)


class SixDomainTypeTests(unittest.TestCase):
    def setUp(self):
        self.packet = fixture()

    def test_all_six_are_concrete_and_proposal_only(self):
        values = (self.packet.project, self.packet.document, self.packet.order, self.packet.subsystem,
                  self.packet.test, self.packet.configuration)
        self.assertEqual(tuple(map(type, values)), DOMAIN_TYPES)
        for value in values:
            self.assertEqual(value.schema_version, "currentcraft-six-types/v1")
            self.assertEqual(value.definition_status, "v1-proposal")
            with self.assertRaises(NotImplementedError):
                value.require_accepted_definition()

    def test_four_types_reuse_canonical_entities(self):
        for value, canonical in ((self.packet.project, Project), (self.packet.document, Document),
                                 (self.packet.order, Order), (self.packet.subsystem, Subsystem)):
            self.assertIsInstance(value, canonical)

    def test_canonical_legacy_constructors_remain_unchanged(self):
        for canonical, values in ((Project, {}), (Document, {"project_id": uid(100)}),
                                  (Order, {"project_id": uid(100)}), (Subsystem, {"project_id": uid(100)})):
            value = canonical(entity_id=uid(700), record_version=4, **values)
            self.assertEqual(value.schema_version, "enterprise-v1.1")
            self.assertEqual((value.entity_id, value.record_version), (uid(700), 4))

    def test_identity_and_record_versions_survive_json_round_trip(self):
        restored = SixTypePacket.model_validate_json(self.packet.model_dump_json())
        for field in ("project", "document", "order", "subsystem", "test", "configuration"):
            self.assertEqual(record_ref(getattr(restored, field)), record_ref(getattr(self.packet, field)))
        self.assertEqual(restored.configuration.binding(), self.packet.configuration.binding())

    def test_types_are_frozen_and_reject_extra_fields(self):
        for field in ("project", "document", "order", "subsystem", "test", "configuration"):
            record = getattr(self.packet, field)
            with self.assertRaises(ValidationError):
                record.entity_id = uid(999)
            with self.assertRaises(ValidationError):
                rebuild(record, auto_approved=True)

    def test_unknown_project_fields_keep_reasons(self):
        project = ProjectType(entity_id=uid(100))
        for name in ("scope", "lifecycle_phase", "configuration_baseline"):
            value = getattr(project, name)
            self.assertIsNone(value.value)
            self.assertEqual(value.epistemic_status, "unknown")
            self.assertTrue(value.missing_reason)

    def test_known_scope_needs_evidence(self):
        with self.assertRaises(ValidationError):
            ProjectType(entity_id=uid(100), scope={"value": "synthetic", "epistemic_status": "observed"})

    def test_project_duplicate_and_self_references_rejected(self):
        for values in ((ref(700), ref(700)), (ref(700), ref(700, 2)), (ref(100),)):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                rebuild(self.packet.project, dependencies=values)

    def test_received_revision_does_not_replace_authorized_revision(self):
        authorization = RevisionAuthorization(revision=ref(202, 7), decision=ref(600), evidence=(ref(900),))
        document = rebuild(self.packet.document, latest_received_revision=fact(ref(202, 8)), authorization=fact(authorization))
        self.assertEqual(document.authorization.value.revision.version, 7)
        self.assertEqual(document.latest_received_revision.value.version, 8)
        with self.assertRaises(PermissionError):
            document.transition("published")

    def test_authorization_needs_exact_decision_and_evidence(self):
        for values in ({"revision": ref(202), "evidence": (ref(900),)},
                       {"revision": ref(202), "decision": ref(600), "evidence": ()},
                       {"revision": ref(202), "decision": ref(600), "evidence": (ref(900), ref(900, 2))}):
            with self.assertRaises(ValidationError):
                RevisionAuthorization(**values)

    def test_document_cannot_derive_from_or_supersede_itself(self):
        for changes in ({"derived_from": (self.packet.document.captured_revision,)},
                        {"supersedes": fact(self.packet.document.captured_revision)}):
            with self.assertRaises(ValidationError):
                rebuild(self.packet.document, **changes)

    def test_order_quantity_zero_is_not_unknown(self):
        line = self.packet.order.lines[0]
        quantity = rebuild(line.quantity.value, amount="0")
        zero = rebuild(line, quantity=fact(quantity))
        self.assertEqual(zero.quantity.value.amount, Decimal(0))
        self.assertIsNone(OrderLine(line=ref(401)).quantity.value)

    def test_quantity_rejects_float_and_negative_and_preserves_units(self):
        quantity = self.packet.order.lines[0].quantity.value
        for amount in (0.1, True, "-1"):
            with self.assertRaises(ValidationError):
                rebuild(quantity, amount=amount)
        other = rebuild(quantity, unit=rebuild(quantity.unit, dictionary_version="2"))
        with self.assertRaises(ValueError):
            quantity.plus(other)

    def test_order_lines_have_unique_identity_even_at_different_versions(self):
        line = self.packet.order.lines[0]
        for other in (line, rebuild(line, line=ref(403, 2))):
            with self.assertRaises(ValidationError):
                rebuild(self.packet.order, lines=(line, other))

    def test_order_line_cannot_silently_change_requested_configuration(self):
        binding = rebuild(self.packet.configuration.binding(), configuration=ref(106, 4))
        line = rebuild(self.packet.order.lines[0], requested_configuration=fact(binding))
        with self.assertRaises(ValidationError):
            rebuild(self.packet.order, lines=(line,))

    def test_order_commitment_and_fulfillment_are_independent(self):
        line = rebuild(self.packet.order.lines[0], fulfillment=(ref(990),))
        self.assertIsNone(line.commitment.value)
        self.assertEqual(line.fulfillment, (ref(990),))
        self.assertEqual(self.packet.order.commitment_evidence, ())

    def test_interface_requires_exact_declared_component_version(self):
        interface = rebuild(self.packet.subsystem.interfaces[0], local_component=ref(404, 2))
        with self.assertRaises(ValidationError):
            rebuild(self.packet.subsystem, interfaces=(interface,))

    def test_realization_requires_exact_declared_component_version(self):
        realization = rebuild(self.packet.subsystem.realizations[0], component=ref(404, 2))
        with self.assertRaises(ValidationError):
            rebuild(self.packet.subsystem, realizations=(realization,))

    def test_subsystem_duplicate_and_self_references_rejected(self):
        for changes in ({"components": (ref(404), ref(404, 2))}, {"dependencies": (ref(104),)},
                        {"interfaces": self.packet.subsystem.interfaces * 2},
                        {"realizations": self.packet.subsystem.realizations * 2}):
            with self.assertRaises(ValidationError):
                rebuild(self.packet.subsystem, **changes)

    def test_external_interface_peer_is_explicit_not_inferred(self):
        interface = self.packet.subsystem.interfaces[0]
        self.assertNotIn(interface.peer, self.packet.subsystem.components)
        with self.assertRaises(ValidationError):
            rebuild(interface, peer=interface.local_component)

    def test_determinate_criterion_requires_expected_observation_and_evidence(self):
        criterion = self.packet.test.criteria[0]
        unknown = {"value": None, "epistemic_status": "unknown", "missing_reason": "not supplied"}
        for changes in ({"expected": unknown}, {"observed": unknown}, {"evidence": ()},
                        {"observed": fact("ready", "inferred")}):
            with self.assertRaises(ValidationError):
                rebuild(criterion, **changes)

    def test_sat_pass_does_not_generate_acceptance_decision(self):
        self.assertEqual(self.packet.test.result.value, "pass")
        self.assertIsNone(self.packet.test.acceptance_decision.value)
        self.assertIsNone(self.packet.test.verification_activity.value)

    def test_sat_pass_requires_all_nonempty_criteria(self):
        for criteria in ((), (TestCriterion(criterion=ref(800)),)):
            with self.assertRaises(ValidationError):
                rebuild(self.packet.test, criteria=criteria)

    def test_sat_pass_requires_observed_configuration_result_and_time(self):
        for changes in ({"observed_configuration": fact(self.packet.configuration.binding(), "inferred")},
                        {"result": fact("pass", "inferred")},
                        {"tested_at": fact(datetime(2020, 1, 1))}):
            with self.assertRaises(ValidationError):
                rebuild(self.packet.test, **changes)

    def test_sat_fail_requires_a_failed_criterion(self):
        with self.assertRaises(ValidationError):
            rebuild(self.packet.test, result=fact("fail"))
        failed = rebuild(self.packet.test.criteria[0], result="fail")
        test = rebuild(self.packet.test, result=fact("fail"), criteria=(failed,))
        self.assertEqual(test.result.value, "fail")

    def test_unexecuted_test_cannot_have_executed_criteria(self):
        with self.assertRaises(ValidationError):
            rebuild(self.packet.test, result=fact("not_run"))

    def test_configuration_selection_is_canonical_and_duplicates_fail(self):
        one = rebuild(self.packet.configuration, selected=(uid(2), uid(1)))
        two = rebuild(self.packet.configuration, selected=(uid(1), uid(2)))
        self.assertEqual(one.binding(), two.binding())
        with self.assertRaises(ValidationError):
            rebuild(one, selected=(uid(1), uid(1)))
        with self.assertRaises(ValidationError):
            rebuild(one, graph_revision=True)

    def test_packet_returns_bound_analysis_without_authority(self):
        receipt = validate_six_type_packet(self.packet)
        self.assertEqual(receipt.consistency, "consistent")
        self.assertEqual(receipt.analysis.model_outcome, "allowed_by_model")
        self.assertEqual(receipt.analysis.evidence_status, "possible")
        self.assertEqual(receipt.configuration, self.packet.configuration.binding())
        self.assertEqual(len(receipt.checked_records), 6)
        self.assertFalse(receipt.grants_authority)

    def test_unknown_bindings_report_gaps_not_successful_readiness(self):
        project = ProjectType(entity_id=uid(100), record_version=2)
        packet = rebuild(self.packet, project=project)
        receipt = validate_six_type_packet(packet)
        self.assertEqual(receipt.consistency, "incomplete")
        self.assertIn("project_baseline_unknown", receipt.gaps)

    def test_inferred_binding_is_not_observed(self):
        document = rebuild(self.packet.document, configuration=fact(self.packet.configuration.binding(), "inferred"))
        receipt = validate_six_type_packet(rebuild(self.packet, document=document))
        self.assertIn("document_not_observed", receipt.gaps)

    def test_wrong_project_versions_fail_for_all_linked_types(self):
        for name in ("document", "order", "subsystem", "test", "configuration"):
            record = getattr(self.packet, name)
            changes = {"project_revision": 3} if name in ("document", "order", "subsystem") else {"project": ref(100, 3)}
            packet = rebuild(self.packet, **{name: rebuild(record, **changes)})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "project_version_mismatch"):
                validate_six_type_packet(packet)

    def test_wrong_configuration_bindings_fail_across_domains(self):
        wrong = rebuild(self.packet.configuration.binding(), configuration=ref(106, 4))
        for name, field in (("project", "configuration_baseline"), ("document", "configuration"), ("subsystem", "configuration")):
            packet = rebuild(self.packet, **{name: rebuild(getattr(self.packet, name), **{field: fact(wrong)})})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "configuration_mismatch"):
                validate_six_type_packet(packet)

    def test_wrong_sat_configuration_fails_even_when_not_executed(self):
        wrong = rebuild(self.packet.configuration.binding(), graph_revision=2)
        test = rebuild(self.packet.test, configuration=wrong, criteria=(), result={"value": None,
            "epistemic_status": "unknown", "missing_reason": "not supplied"})
        with self.assertRaisesRegex(ValueError, "test_configuration_mismatch"):
            validate_six_type_packet(rebuild(self.packet, test=test))

    def test_wrong_document_basis_revision_is_rejected(self):
        test = rebuild(self.packet.test, basis=(ref(202, 8),))
        with self.assertRaisesRegex(ValueError, "test_document_revision_mismatch"):
            validate_six_type_packet(rebuild(self.packet, test=test))

    def test_realization_must_be_selected_feature(self):
        realization = rebuild(self.packet.subsystem.realizations[0], feature_id=uid(99))
        subsystem = rebuild(self.packet.subsystem, realizations=(realization,))
        with self.assertRaisesRegex(ValueError, "realization_feature_not_selected"):
            validate_six_type_packet(rebuild(self.packet, subsystem=subsystem))

    def test_exact_graph_digest_is_checked(self):
        graph = rebuild(self.packet.graph, revision=2)
        with self.assertRaisesRegex(ValueError, "pin this exact graph"):
            validate_six_type_packet(rebuild(self.packet, graph=graph))

    def test_known_invalid_model_is_not_silently_repaired(self):
        feature = rebuild(self.packet.graph.features[0], status="retired")
        graph = rebuild(self.packet.graph, features=(feature,))
        config = rebuild(self.packet.configuration, graph_digest=graph.digest())
        bound = config.binding()
        project = rebuild(self.packet.project, configuration_baseline=fact(bound))
        document = rebuild(self.packet.document, configuration=fact(bound))
        line = rebuild(self.packet.order.lines[0], requested_configuration=fact(bound))
        order = rebuild(self.packet.order, requested_configuration=fact(bound), lines=(line,))
        subsystem = rebuild(self.packet.subsystem, configuration=fact(bound))
        test = rebuild(self.packet.test, configuration=bound, observed_configuration=fact(bound))
        receipt = validate_six_type_packet(SixTypePacket(project=project, document=document, order=order,
            subsystem=subsystem, test=test, configuration=config, graph=graph))
        self.assertEqual(receipt.consistency, "consistent")
        self.assertEqual(receipt.analysis.model_outcome, "violates_model")
        self.assertFalse(receipt.grants_authority)

    def test_old_wire_family_is_not_silently_upgraded(self):
        with self.assertRaises(ValidationError):
            rebuild(self.packet.project, schema_version="enterprise-v1.1")


if __name__ == "__main__":
    unittest.main()
