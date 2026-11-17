"""Review gate tests only. No S3 deletion operations exist in this gate."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app.application.persistence.deletion_review import ObjectInventory, DeletionReviewGate, DeletionBlocked
from app.infrastructure.persistence import build_memory

AT = datetime(2026, 11, 12, 21, 53, tzinfo=timezone.utc)


class Inventory:
    def __init__(self):
        self.snapshot = ObjectInventory(object_ref='blob:one', content_sha256='a'*64, storage_version='sha256:'+ 'a'*64,
                                         generation='1', reference_count=0, hold_count=0, lease_count=0,
                                         retention_allows_delete=True, available=True, observed_at=AT)
    def inspect(self, ref):
        return self.snapshot


class Authority:
    allowed = True
    def can_review_deletion(self, principal, ref):
        return self.allowed and principal == 'reviewer'


class DeletionReviewTests(unittest.TestCase):
    def setUp(self):
        self.inventory, self.authority, self.uow = Inventory(), Authority(), build_memory()
        self.gate = DeletionReviewGate(self.uow, self.inventory, self.authority)
    def request(self):
        return self.gate.request('blob:one', 'requester', 'unreferenced candidate', AT)
    def approve(self, r):
        return self.gate.decide(r.review_id, 'reviewer', True, 'reviewed scope and policy', AT)

    def test_unreferenced_never_auto_approved(self):
        r = self.request()
        self.assertEqual(r.status, 'pending')
        with self.assertRaises(DeletionBlocked): self.gate.check_review(r.review_id, AT)

    def test_independent_authority_required(self):
        r = self.request()
        for principal in ('requester', 'stranger'):
            with self.assertRaises(DeletionBlocked): self.gate.decide(r.review_id, principal, True, 'ok', AT)

    def test_approved_decision_and_full_history(self):
        r = self.request(); self.approve(r)
        self.assertEqual(self.gate.check_review(r.review_id, AT).status, 'approved')
        with self.uow() as u:
            history=u.aggregates.history('storage.deletion_review', r.review_id)
            self.assertEqual([v.payload['status'] for v in history], ['pending','approved'])
        with self.assertRaises(DeletionBlocked): self.approve(r)

    def test_rejection_never_qualifies(self):
        r=self.request(); self.gate.decide(r.review_id,'reviewer',False,'keep it',AT)
        with self.assertRaises(DeletionBlocked): self.gate.check_review(r.review_id,AT)

    def test_refs_holds_leases_unknown_retention_unavailable_block(self):
        for patch in ({'reference_count':1},{'hold_count':1},{'lease_count':1},
                      {'retention_allows_delete':False},{'available':False}):
            original=self.inventory.snapshot
            self.inventory.snapshot=original.model_copy(update=patch)
            with self.assertRaises(DeletionBlocked): self.request()
            self.inventory.snapshot=original

    def test_changed_identity_or_inventory_requires_new_review(self):
        r=self.request()
        for patch in ({'generation':'2'}, {'storage_version':'replacement'}, {'content_sha256':'b'*64}):
            original=self.inventory.snapshot;self.inventory.snapshot=original.model_copy(update=patch)
            with self.assertRaises(DeletionBlocked): self.approve(r)
            self.inventory.snapshot=original

    def test_approval_revalidated_and_authority_revocation_blocks(self):
        r=self.request();self.approve(r)
        self.inventory.snapshot=self.inventory.snapshot.model_copy(update={'generation':'2'})
        with self.assertRaises(DeletionBlocked):self.gate.check_review(r.review_id,AT)
        self.inventory.snapshot=self.inventory.snapshot.model_copy(update={'generation':'1'})
        self.authority.allowed=False
        with self.assertRaises(DeletionBlocked):self.gate.check_review(r.review_id,AT)

    def test_expiry_stale_future_and_invalid_deadline(self):
        r=self.request()
        with self.assertRaises(DeletionBlocked):self.gate.decide(r.review_id,'reviewer',True,'ok',AT+timedelta(days=1))
        for dt in (AT-timedelta(minutes=6), AT+timedelta(seconds=1)):
            self.inventory.snapshot=self.inventory.snapshot.model_copy(update={'observed_at':dt})
            with self.assertRaises(DeletionBlocked):self.request()
        with self.assertRaises(ValueError):self.gate.request('blob:one','requester','why',AT,ttl=timedelta(days=2))

    def test_missing_inventory_never_creates_review(self):
        def fail(ref):raise ConnectionError('inventory unavailable')
        self.inventory.inspect=fail
        with self.assertRaises(ConnectionError):self.request()

# Same gate contract on the SQL repository stand-in, not merely in-memory state.
try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


@unittest.skipUnless(HAS_DUCKDB, 'duckdb stand-in not installed')
class SqlDeletionReviewTests(DeletionReviewTests):
    def setUp(self):
        from app.infrastructure.persistence import build_duckdb_standin
        self.inventory, self.authority, self.uow = Inventory(), Authority(), build_duckdb_standin()
        self.gate = DeletionReviewGate(self.uow, self.inventory, self.authority)
    def tearDown(self):
        self.uow.raw_connection.close()
