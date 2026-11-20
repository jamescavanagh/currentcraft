"""P4 lifecycle vocabulary. Design: docs/domain/P4_DESIGN_CONTRACTS.md."""
from typing import ClassVar
from app.domain.shared.versioning import Code, Label, P4Record


class LifecycleState(P4Record):
    """Named lifecycle state; display labels are not process control effects."""
    SOURCE_CLASS: ClassVar[str] = "LifecycleState"
    code: Code
    display_name: Label
    initial: bool = False
    terminal: bool = False
