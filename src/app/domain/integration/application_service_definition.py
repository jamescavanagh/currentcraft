"""Unreviewed domain scaffold. Design source: docs/domain/DOMAIN_SCAFFOLD.md."""

from typing import ClassVar

from app.domain.shared.scaffold_record import ScaffoldRecord


class ApplicationService(ScaffoldRecord):
    """Descriptive service metadata only. Executable orchestration lives in app.application."""

    SOURCE_CLASS: ClassVar[str] = 'ApplicationService'
    NOTE: ClassVar[str] = 'Descriptive service metadata only. Executable orchestration lives in app.application.'
