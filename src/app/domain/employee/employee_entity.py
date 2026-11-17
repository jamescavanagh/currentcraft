"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Employee(ScaffoldRecord):
    """Employee resource. Distinct from Contributor, not a subtype of it; permissions unresolved."""

    SOURCE_CLASS: ClassVar[str] = 'Employee'
    NOTE: ClassVar[str] = 'Employee resource. Distinct from Contributor, not a subtype of it; permissions unresolved.'
