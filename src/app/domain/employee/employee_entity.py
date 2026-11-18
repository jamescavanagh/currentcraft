"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.shared.facts import Fact, unknown
from app.domain.workforce.resource import Resource


class Employee(Resource):
    """Employee resource; never a subtype of third-party Contributor."""
    SOURCE_CLASS: ClassVar[str] = 'Employee'
    kind: Literal["employee"] = "employee"
    employment_kind: Fact[Literal["full_time", "part_time", "temporary"]] = Field(default_factory=unknown)
