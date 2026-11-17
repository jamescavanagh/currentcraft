"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Stakeholder(ScaffoldRecord):
    """Contextual relationship between a party and a context. Not a person subtype; grants no authority."""

    SOURCE_CLASS: ClassVar[str] = 'Stakeholder'
    NOTE: ClassVar[str] = 'Contextual relationship between a party and a context. Not a person subtype; grants no authority.'
