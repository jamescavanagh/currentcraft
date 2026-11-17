"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class ProductDefinition(ScaffoldRecord):
    """Catalog definition: model and manufacturer part information."""

    SOURCE_CLASS: ClassVar[str] = '(addition)'
    NOTE: ClassVar[str] = 'Catalog definition: model and manufacturer part information.'
