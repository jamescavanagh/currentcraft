"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class Phase(ScaffoldRecord):
    """Project lifecycle phase. Never the simulator physics phase."""

    SOURCE_CLASS: ClassVar[str] = 'Phase'
    NOTE: ClassVar[str] = 'Project lifecycle phase. Never the simulator physics phase.'
