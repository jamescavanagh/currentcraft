"""Need, Scope and the Subsystem location link (docs/domain/NEEDS_AND_SCOPE.md). Capture only."""
import sys, unittest
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from pydantic import ValidationError  # noqa: E402

from app.domain.estimation.need import Need  # noqa: E402
from app.domain.estimation.scope import Scope  # noqa: E402
from app.domain.project.subsystem import Subsystem  # noqa: E402


def uid(n):
    return UUID(int=n)


def fact(value):
    return {'value': value, 'epistemic_status': 'observed', 'evidence_ids': (uid(900),)}


class NeedCapture(unittest.TestCase):
    def test_minimal_need_is_unknown_not_empty(self):
        need = Need(entity_id=uid(1), project_id=uid(100))
        self.assertEqual(need.statement.epistemic_status, 'unknown')
        self.assertEqual(need.document_ids, ())
        self.assertEqual(need.definition_status, 'v1-proposal')

    def test_need_links_documents_explicitly(self):
        need = Need(entity_id=uid(1), project_id=uid(100), statement=fact('synthetic need'), document_ids=(uid(2), uid(3)))
        self.assertEqual(need.document_ids, (uid(2), uid(3)))
        with self.assertRaisesRegex(ValidationError, 'duplicate document'):
            Need(entity_id=uid(1), project_id=uid(100), document_ids=(uid(2), uid(2)))

    def test_need_grants_nothing(self):
        need = Need(entity_id=uid(1), project_id=uid(100))
        with self.assertRaises(NotImplementedError):
            need.require_accepted_definition()
        for bad in ({'approved': True}, {'estimate': 1}, {'project_id': 'PRJ-1'}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                Need(entity_id=uid(1), **({'project_id': uid(100)} | bad))


class ScopeCapture(unittest.TestCase):
    def test_scope_categories_are_labor_or_service_only(self):
        for cat in ('internal_labor', 'outsourced_labor', 'vendor_service'):
            Scope(entity_id=uid(5), project_id=uid(100), category=fact(cat))
        for cat in ('materials', 'bom', 'travel'):
            with self.subTest(cat=cat), self.assertRaises(ValidationError):
                Scope(entity_id=uid(5), project_id=uid(100), category=fact(cat))

    def test_scope_document_link_is_a_fact(self):
        s = Scope(entity_id=uid(5), project_id=uid(100), document_id=fact(uid(2)))
        self.assertEqual(s.document_id.value, uid(2))
        self.assertEqual(Scope(entity_id=uid(5), project_id=uid(100)).document_id.epistemic_status, 'unknown')

    def test_round_trip(self):
        s = Scope(entity_id=uid(5), project_id=uid(100), statement=fact('synthetic scope'))
        self.assertEqual(Scope.model_validate_json(s.model_dump_json()), s)


class SubsystemLocation(unittest.TestCase):
    def test_location_link_defaults_to_unknown_and_identity_is_unchanged(self):
        before = {'entity_id': uid(104), 'project_id': uid(100)}
        s = Subsystem(**before)
        self.assertEqual(s.location_id.epistemic_status, 'unknown')
        self.assertEqual((s.entity_id, s.project_id, s.record_version), (uid(104), uid(100), 1))

    def test_location_link_requires_evidence(self):
        self.assertEqual(Subsystem(entity_id=uid(104), project_id=uid(100), location_id=fact(uid(7))).location_id.value, uid(7))
        with self.assertRaises(ValidationError):
            Subsystem(entity_id=uid(104), project_id=uid(100), location_id={'value': uid(7), 'epistemic_status': 'observed'})


if __name__ == '__main__':
    unittest.main()
