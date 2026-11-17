"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class ManufacturerRep(ScaffoldRecord):
    """Representation relationship between a manufacturer and a representative party."""

    SOURCE_CLASS: ClassVar[str] = 'ManufacturerRep'
    NOTE: ClassVar[str] = 'Representation relationship between a manufacturer and a representative party.'
