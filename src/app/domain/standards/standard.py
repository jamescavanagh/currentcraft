"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Standard(ScaffoldRecord):
    """Definition pending review."""

    SOURCE_CLASS: ClassVar[str] = 'Standard'
    NOTE: ClassVar[str] = 'Definition pending review.'
