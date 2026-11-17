"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Contributor(ScaffoldRecord):
    """Third-party labor resource. Shared resource base and permissions unresolved."""

    SOURCE_CLASS: ClassVar[str] = 'Contributor'
    NOTE: ClassVar[str] = 'Third-party labor resource. Shared resource base and permissions unresolved.'
