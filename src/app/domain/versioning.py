"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class VersionedEntity(ScaffoldRecord):
    """Versioning base name. No versioning behavior implemented here."""

    SOURCE_CLASS: ClassVar[str] = 'VersionedEntity'
    NOTE: ClassVar[str] = 'Versioning base name. No versioning behavior implemented here.'
