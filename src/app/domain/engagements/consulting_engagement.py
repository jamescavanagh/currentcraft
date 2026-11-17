"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Consultant(ScaffoldRecord):
    """Third-party approver engagement. Approval scope must be explicit per decision."""

    SOURCE_CLASS: ClassVar[str] = 'Consultant'
    NOTE: ClassVar[str] = 'Third-party approver engagement. Approval scope must be explicit per decision.'
