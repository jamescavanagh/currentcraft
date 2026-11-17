"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class ProductOnlyVendor(ScaffoldRecord):
    """Vendor subtype: sells products only, such as a distributor."""

    SOURCE_CLASS: ClassVar[str] = '(addition)'
    NOTE: ClassVar[str] = 'Vendor subtype: sells products only, such as a distributor.'
