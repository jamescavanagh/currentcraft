"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class WorkflowDefinition(ScaffoldRecord):
    """Definition pending review."""

    SOURCE_CLASS: ClassVar[str] = 'WorkflowDefinition'
    NOTE: ClassVar[str] = 'Definition pending review.'
