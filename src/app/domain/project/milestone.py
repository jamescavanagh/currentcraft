"""P4 planned milestone and evidenced occurrence; sign-off is separate."""
from datetime import date, datetime
from typing import ClassVar
from uuid import UUID
from pydantic import model_validator
from app.domain.shared.versioning import Label, P4Record, VersionRef, aware, unique


class Milestone(P4Record):
    """Planned date is not occurrence, and occurrence is not sign-off."""
    SOURCE_CLASS: ClassVar[str] = "Milestone"
    project_id: UUID
    name: Label
    planned_date: date | None = None
    occurred_at: datetime | None = None
    occurrence_evidence: tuple[VersionRef, ...] = ()

    @model_validator(mode="after")
    def occurrence(self):
        unique(self.occurrence_evidence, "occurrence evidence")
        if (self.occurred_at is None) != (not self.occurrence_evidence):
            raise ValueError("occurrence time and evidence go together")
        if self.occurred_at is not None:
            aware(self.occurred_at)
        return self
