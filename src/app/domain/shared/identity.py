"""Opaque IDs and source references. Design: docs/domain/V1_DOMAIN.md."""
from typing import Annotated, NewType
from uuid import UUID
from pydantic import BaseModel, ConfigDict, StringConstraints

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=False, min_length=1, pattern=r"\S")]
ProjectId = NewType("ProjectId", UUID)
PartyId = NewType("PartyId", UUID)
ResourceId = NewType("ResourceId", UUID)
PhaseId = NewType("PhaseId", UUID)
SubsystemId = NewType("SubsystemId", UUID)
TaskId = NewType("TaskId", UUID)
ProductId = NewType("ProductId", UUID)
AssetId = NewType("AssetId", UUID)
DocumentId = NewType("DocumentId", UUID)
EvidenceId = NewType("EvidenceId", UUID)
BOMId = NewType("BOMId", UUID)
WBSId = NewType("WBSId", UUID)
ShipmentId = NewType("ShipmentId", UUID)


class ExternalReference(BaseModel):
    """Source namespace plus source key; neither becomes internal identity."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    namespace: Text
    key: Text
