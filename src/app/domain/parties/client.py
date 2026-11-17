"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Client(ScaffoldRecord):
    """Client party; may hold scope outside the delivering organization."""

    SOURCE_CLASS: ClassVar[str] = 'Client'
    NOTE: ClassVar[str] = 'Client party; may hold scope outside the delivering organization.'
