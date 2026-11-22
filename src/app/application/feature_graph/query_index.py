"""Immutable query indexes for exact feature-graph revisions."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping, TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.domain.operand.feature_graph import FeatureGraphRevision


@dataclass(frozen=True, slots=True)
class ConstraintArc:
    """One sourced constraint indexed by its antecedent/left feature."""
    kind: Literal["requires", "excludes"]
    target: UUID
    constraint_id: UUID


@dataclass(frozen=True, slots=True)
class FeatureGraphQueryIndex:
    """Compiled lookups bound to one immutable graph revision and digest."""
    graph_id: UUID
    revision: int
    graph_digest: str
    feature_ids: frozenset[UUID]
    retired_feature_ids: frozenset[UUID]
    mandatory_feature_ids: frozenset[UUID]
    constraints_by_left: Mapping[UUID, tuple[ConstraintArc, ...]]
    complete_observations_by_selection: Mapping[frozenset[UUID], tuple[UUID, ...]]


def compile_feature_graph(snapshot: "FeatureGraphRevision") -> FeatureGraphQueryIndex:
    """Build per-revision lookup tables once, at the infrastructure boundary."""
    features = snapshot.features
    constraints: dict[UUID, list[ConstraintArc]] = {}
    for item in snapshot.constraints:
        constraints.setdefault(item.left, []).append(
            ConstraintArc(item.kind, item.right, item.constraint_id)
        )

    complete_observations: dict[frozenset[UUID], list[UUID]] = {}
    for observation in snapshot.observations:
        if observation.complete:
            complete_observations.setdefault(frozenset(observation.present), []).append(
                observation.observation_id
            )

    return FeatureGraphQueryIndex(
        graph_id=snapshot.graph_id,
        revision=snapshot.revision,
        graph_digest=snapshot.digest(),
        feature_ids=frozenset(item.feature_id for item in features),
        retired_feature_ids=frozenset(
            item.feature_id for item in features if item.status == "retired"
        ),
        mandatory_feature_ids=frozenset(
            item.feature_id
            for item in features
            if item.status == "active" and item.mandatory
        ),
        constraints_by_left=MappingProxyType(
            {key: tuple(value) for key, value in constraints.items()}
        ),
        complete_observations_by_selection=MappingProxyType(
            {key: tuple(value) for key, value in complete_observations.items()}
        ),
    )
