"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Equipment(ScaffoldRecord):
    """Definition pending review."""

    SOURCE_CLASS: ClassVar[str] = 'Equipment'
    NOTE: ClassVar[str] = 'Definition pending review.'


class IntegrationMaterial(ScaffoldRecord):
    """Definition pending review."""

    SOURCE_CLASS: ClassVar[str] = 'IntegrationMaterial'
    NOTE: ClassVar[str] = 'Definition pending review.'


class Product(ScaffoldRecord):
    """Source name only. Target split: ProductDefinition and AssetInstance."""

    SOURCE_CLASS: ClassVar[str] = 'Product'
    NOTE: ClassVar[str] = 'Source name only. Target split: ProductDefinition and AssetInstance.'
