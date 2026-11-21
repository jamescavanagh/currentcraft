"""Read-only graph analysis plus explicit append through a repository port."""
from typing import Protocol
from uuid import UUID

from app.domain.operand.feature_graph import FeatureGraphRevision
from .contracts import AsOfRequest, ConfigurationRequest, ConfigurationResult, FeatureGraphDiff


class FeatureGraphRepository(Protocol):
    """Revision history port; adapter enforces append/CAS and history invariants."""
    def append(self, snapshot: FeatureGraphRevision, *, expected_revision: int) -> None: ...
    def history(self, graph_id: UUID) -> tuple[FeatureGraphRevision, ...]: ...


def validate_configuration(graph: FeatureGraphRevision, request: ConfigurationRequest) -> ConfigurationResult:
    if (request.graph_id, request.graph_revision, request.graph_digest) != (graph.graph_id, graph.revision, graph.digest()):
        raise ValueError("configuration request does not pin this exact graph")
    selected = set(request.selected)
    features = {f.feature_id: f for f in graph.features}
    violations = ["unknown:" + str(key) for key in selected - features.keys()]
    for feature in graph.features:
        if feature.status == "retired" and feature.feature_id in selected:
            violations.append("retired:" + str(feature.feature_id))
        if feature.status == "active" and feature.mandatory and feature.feature_id not in selected:
            violations.append("mandatory:" + str(feature.feature_id))
    for constraint in graph.constraints:
        if constraint.left in selected and ((constraint.kind == "requires" and constraint.right not in selected) or
                                            (constraint.kind == "excludes" and constraint.right in selected)):
            violations.append(constraint.kind + ":" + str(constraint.constraint_id))
    observations = tuple(o.observation_id for o in graph.observations if o.complete and set(o.present) == selected)
    allowed = not violations
    return ConfigurationResult(configuration_id=request.configuration_id, graph_id=graph.graph_id,
        graph_revision=graph.revision, graph_digest=graph.digest(), request_digest=request.digest(),
        model_outcome="allowed_by_model" if allowed else "violates_model",
        evidence_status="observed_configuration" if observations else ("possible" if allowed else "not_model_permitted"),
        violations=tuple(sorted(violations)), observation_ids=observations)


def compare_snapshots(before: FeatureGraphRevision, after: FeatureGraphRevision) -> FeatureGraphDiff:
    if before.graph_id != after.graph_id or before.revision >= after.revision:
        raise ValueError("comparison requires ordered revisions of the same graph")
    left = {f.feature_id: f for f in before.features}
    right = {f.feature_id: f for f in after.features}
    shared = left.keys() & right.keys()
    retired = {key for key in shared if left[key].status == "active" and right[key].status == "retired"}
    carried = {key for key in shared if left[key] == right[key]}
    return FeatureGraphDiff(graph_id=before.graph_id, before_revision=before.revision, after_revision=after.revision,
        before_digest=before.digest(), after_digest=after.digest(), introduced=tuple(sorted(right.keys() - left.keys())),
        carried=tuple(sorted(carried)), changed=tuple(sorted(shared - retired - carried)),
        retired=tuple(sorted(retired)), no_longer_listed=tuple(sorted(left.keys() - right.keys())))


class FeatureGraphService:
    def __init__(self, repository: FeatureGraphRepository):
        self.repository = repository

    def append(self, snapshot: FeatureGraphRevision, *, expected_revision: int) -> None:
        self.repository.append(snapshot, expected_revision=expected_revision)

    def as_of(self, request: AsOfRequest) -> FeatureGraphRevision | None:
        eligible = [s for s in self.repository.history(request.graph_id)
                    if s.valid_from <= request.effective_at and s.recorded_at <= request.known_at]
        return max(eligible, key=lambda s: (s.valid_from, s.revision)) if eligible else None

    def validate(self, request: ConfigurationRequest) -> ConfigurationResult:
        for snapshot in self.repository.history(request.graph_id):
            if snapshot.revision == request.graph_revision:
                return validate_configuration(snapshot, request)
        raise ValueError("selected graph revision not found")
