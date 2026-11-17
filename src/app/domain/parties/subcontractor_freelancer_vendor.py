"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class SubcontractorFreelancerVendor(ScaffoldRecord):
    """Vendor subtype: subcontractor or freelancer."""

    SOURCE_CLASS: ClassVar[str] = '(addition)'
    NOTE: ClassVar[str] = 'Vendor subtype: subcontractor or freelancer.'
