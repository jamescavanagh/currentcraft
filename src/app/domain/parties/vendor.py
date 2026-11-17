"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Vendor(ScaffoldRecord):
    """Vendor party. Four subtype meanings exist; overlap policy unresolved."""

    SOURCE_CLASS: ClassVar[str] = 'Vendor'
    NOTE: ClassVar[str] = 'Vendor party. Four subtype meanings exist; overlap policy unresolved.'
