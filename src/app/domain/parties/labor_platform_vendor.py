"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class LaborPlatformVendor(ScaffoldRecord):
    """Vendor subtype: platform through which labor is booked. Not the provider booked through it."""

    SOURCE_CLASS: ClassVar[str] = '(addition)'
    NOTE: ClassVar[str] = 'Vendor subtype: platform through which labor is booked. Not the provider booked through it.'
