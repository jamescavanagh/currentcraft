"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Order(ScaffoldRecord):
    """Commercial entity, separate from any document that represents it."""

    SOURCE_CLASS: ClassVar[str] = 'Order'
    NOTE: ClassVar[str] = 'Commercial entity, separate from any document that represents it.'
