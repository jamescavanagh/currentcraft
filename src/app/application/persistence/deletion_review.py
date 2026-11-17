"""Application-only deletion review gate. No S3 operations and no executable deletion token.

Trusted inventory and reviewer authority are injected ports. Records reuse aggregate CAS/history.
An approval is a time-bounded review decision, not proof that bytes have been erased or a concurrency lock.
"""
from datetime import datetime, timedelta
from typing import Literal, Protocol, Optional
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from app.application.common.contracts import _Frozen
from .contracts import VersionedRecord, _aware
from .ports import UnitOfWorkFactory


class DeletionBlocked(Exception):
    """Review prerequisite or authority missing. No storage action is authorized."""


class ObjectInventory(_Frozen):
    object_ref: str = Field(min_length=1, max_length=200, description="Opaque managed object reference, not a presigned URL.")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Verified SHA-256, never an assumed ETag.")
    storage_version: str = Field(min_length=1, max_length=200, description="Exact version identity or trusted immutable content identity.")
    generation: str = Field(min_length=1, max_length=120, description="Authoritative generation changing on refs/holds/leases/policy/availability changes.")
    reference_count: int = Field(ge=0, description="Includes historical, shared and current retaining references.")
    hold_count: int = Field(ge=0, description="Active retention/legal/review holds.")
    lease_count: int = Field(ge=0, description="Active ingestion/read/extraction leases.")
    retention_allows_delete: bool = Field(description="Explicit approved policy permits deletion; unknown means false.")
    available: bool = Field(description="Exact object identity was verified present.")
    observed_at: datetime = Field(description="Timezone-aware authoritative inventory observation.")

    @model_validator(mode='after')
    def aware(self):
        _aware(self.observed_at, 'observed_at')
        return self


class DeletionReview(_Frozen):
    review_id: UUID = Field(description="Opaque candidate review id.")
    snapshot: ObjectInventory = Field(description="Evidence reviewed, including object identity and inventory generation.")
    requester: str = Field(min_length=1, description="Authenticated principal requesting review.")
    reason: str = Field(min_length=1, max_length=500, description="Why deletion is proposed.")
    requested_at: datetime = Field(description="Request time.")
    expires_at: datetime = Field(description="Review and approval deadline; expiry never means approval.")
    status: Literal['pending', 'approved', 'rejected'] = Field(default='pending', description="Recorded review decision, not deletion state.")
    reviewer: Optional[str] = Field(default=None, description="Authenticated authorized reviewer, distinct from requester.")
    decision_reason: Optional[str] = Field(default=None, max_length=500, description="Review rationale.")
    decided_at: Optional[datetime] = Field(default=None, description="Decision timestamp.")


class InventoryPort(Protocol):
    def inspect(self, object_ref: str) -> ObjectInventory: ...


class ReviewAuthorityPort(Protocol):
    def can_review_deletion(self, principal: str, object_ref: str) -> bool: ...


def _eligible(snapshot, at):
    _aware(at, 'at')
    age = (at - snapshot.observed_at).total_seconds()
    if not 0 <= age <= 300:
        raise DeletionBlocked('inventory must be current (within five minutes, never future-dated)')
    if snapshot.reference_count or snapshot.hold_count or snapshot.lease_count:
        raise DeletionBlocked('retaining references, holds or active leases block deletion review')
    if not snapshot.retention_allows_delete or not snapshot.available:
        raise DeletionBlocked('retention clearance and verified object availability required')


def _same(review, snapshot, at):
    _eligible(snapshot, at)
    keys = ('object_ref', 'content_sha256', 'storage_version', 'generation')
    if any(getattr(review.snapshot, key) != getattr(snapshot, key) for key in keys):
        raise DeletionBlocked('object or inventory changed; request a new review')
    if at >= review.expires_at:
        raise DeletionBlocked('review expired; request a new review')


class DeletionReviewGate:
    """Store pending candidates and decisions in the existing versioned aggregate repository.

    Caller supplies authenticated identities; never trust a request-body identity. Inventory must cover every
    managed retaining reference, not just current project-document links. Missing providers mean no gate service.
    """
    def __init__(self, uow_factory: UnitOfWorkFactory, inventory: InventoryPort, authority: ReviewAuthorityPort):
        self.uow_factory, self.inventory, self.authority = uow_factory, inventory, authority

    @staticmethod
    def _save(uow, review, expected, at):
        uow.aggregates.save(VersionedRecord(aggregate_type='storage.deletion_review', aggregate_id=review.review_id,
                                           version=(expected or 0) + 1, schema_version='v1',
                                           payload=review.model_dump(mode='json'), recorded_at=at), expected)

    @staticmethod
    def _load(uow, review_id):
        record = uow.aggregates.get('storage.deletion_review', review_id)
        if record is None:
            raise KeyError('deletion review not found')
        return DeletionReview.model_validate(record.payload), record.version

    def request(self, object_ref, requester, reason, at, ttl=timedelta(hours=24)):
        if not timedelta(0) < ttl <= timedelta(hours=24):
            raise ValueError('review lifetime must be positive and no longer than 24 hours')
        snapshot = self.inventory.inspect(object_ref)
        if snapshot.object_ref != object_ref:
            raise DeletionBlocked('inventory returned a different object')
        _eligible(snapshot, at)
        review = DeletionReview(review_id=uuid4(), snapshot=snapshot, requester=requester, reason=reason,
                                requested_at=at, expires_at=at + ttl)
        with self.uow_factory() as uow:
            self._save(uow, review, None, at)
            uow.commit()
        return review

    def decide(self, review_id, reviewer, approve, reason, at):
        _aware(at, 'at')
        if type(approve) is not bool or not reason or not reason.strip() or len(reason) > 500:
            raise ValueError('explicit boolean decision and review reason required')
        with self.uow_factory() as uow:
            review, version = self._load(uow, review_id)
            if review.status != 'pending':
                raise DeletionBlocked('review already decided')
            if reviewer == review.requester or not self.authority.can_review_deletion(reviewer, review.snapshot.object_ref):
                raise DeletionBlocked('independent authorized reviewer required')
            if at < review.requested_at or at >= review.expires_at:
                raise DeletionBlocked('decision outside review lifetime')
            if approve:
                _same(review, self.inventory.inspect(review.snapshot.object_ref), at)
            decided = review.model_copy(update={'status': 'approved' if approve else 'rejected', 'reviewer': reviewer,
                                                 'decision_reason': reason, 'decided_at': at})
            self._save(uow, decided, version, at)
            uow.commit()
        return decided

    def check_review(self, review_id, at):
        """Read-only revalidation. NOT a deletion permit; cannot close a check/delete race outside this service."""
        with self.uow_factory() as uow:
            review, _ = self._load(uow, review_id)
        if review.status != 'approved':
            raise DeletionBlocked('explicit approval required')
        if at < review.decided_at:
            raise DeletionBlocked('validation predates review decision')
        if not self.authority.can_review_deletion(review.reviewer, review.snapshot.object_ref):
            raise DeletionBlocked('review authority revoked')
        _same(review, self.inventory.inspect(review.snapshot.object_ref), at)
        return review


REVIEW_CONTRACTS = (ObjectInventory, DeletionReview)
