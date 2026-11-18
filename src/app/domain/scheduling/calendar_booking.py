"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import TimeWindow
from app.domain.shared.identity import ProjectId, ResourceId, TaskId


class CalendarBooking(VersionedEntity):
    """Captured time-bounded booking; never a live allocation or permission."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["calendar_booking"] = "calendar_booking"
    project_id: ProjectId
    resource_id: ResourceId
    task_id: TaskId
    window: TimeWindow
