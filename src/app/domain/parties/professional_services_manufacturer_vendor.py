"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class ProfessionalServicesManufacturerVendor(ScaffoldRecord):
    """Vendor subtype: manufacturer that also sells professional services."""

    SOURCE_CLASS: ClassVar[str] = '(addition)'
    NOTE: ClassVar[str] = 'Vendor subtype: manufacturer that also sells professional services.'
