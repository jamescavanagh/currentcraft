"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class CredentialDefinition(ScaffoldRecord):
    """Definition pending review."""

    SOURCE_CLASS: ClassVar[str] = 'CredentialDefinition'
    NOTE: ClassVar[str] = 'Definition pending review.'
