"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class AssetInstance(ScaffoldRecord):
    """Physical unit linked to a ProductDefinition. Bulk materials get no invented serial identity."""

    SOURCE_CLASS: ClassVar[str] = '(addition)'
    NOTE: ClassVar[str] = 'Physical unit linked to a ProductDefinition. Bulk materials get no invented serial identity.'
