"""Typed supported contexts. Contract/decision branches remain undefined, not fabricated."""
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field
from .identity import ProjectId, SubsystemId


class ProjectContext(BaseModel):
    """Project-scoped relationship context; no authority implied."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["project"] = "project"
    project_id: ProjectId


class SubsystemContext(BaseModel):
    """Subsystem within an explicitly asserted project, checked at the application boundary."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["subsystem"] = "subsystem"
    project_id: ProjectId
    subsystem_id: SubsystemId


Context = Annotated[Union[ProjectContext, SubsystemContext], Field(discriminator="kind")]
