"""Read-only graph analysis plus explicit append through a repository port."""
from typing import Protocol
from uuid import UUID

from app.domain.operand.feature_graph import FeatureGraphRevision
from .contracts import AsOfRequest, ConfigurationRequest, ConfigurationResult, FeatureGraphDiff
from .query_index import ConstraintArc, FeatureGraphQueryIndex, compile_feature_graph


class FeatureGraphRepository(Protocol):
    """Revision history port; adapter enforces append/CAS and history invariants."""
    def append(self, snapshot: FeatureGraphRevision, *, expected_revision: int) -> None: ...
    def history(self, graph_id: UUID) -> tuple[FeatureGraphRevision, ...]: ...
    def get_revision(self, graph_id: UUID, revision: int) -> FeatureGraphRevision | None: ...
    def query_index(self, graph_id: UUID, revision: int) -> FeatureGraphQueryIndex | None: ...


def _validate_with_index(
    graph: FeatureGraphRevision,
    request: ConfigurationRequest,
    index: FeatureGraphQueryIndex,
) -> ConfigurationResult:
    if (graph.graph_id, graph.revision) != (index.graph_id, index.revision):
        raise ValueError("query index does not match this graph revision")
    if (request.graph_id, request.graph_revision, request.graph_digest) != (
        index.graph_id, index.revision, index.graph_digest
    ):
        raise ValueError("configuration request does not pin this exact graph")

    selected = set(request.selected)
    violations = {"unknown:" + str(key) for key in selected - index.feature_ids}
    violations.update(
        "retired:" + str(key) for key in selected & index.retired_feature_ids
    )
    violations.update(
        "mandatory:" + str(key)
        for key in index.mandatory_feature_ids - selected
    )
    for source in selected:
        for arc in index.constraints_by_left.get(source, ()):
            if arc.kind == "requires" and arc.target not in selected:
                violations.add("requires:" + str(arc.constraint_id))
            elif arc.kind == "excludes" and arc.target in selected:
                violations.add("excludes:" + str(arc.constraint_id))

    observations = index.complete_observations_by_selection.get(
        frozenset(selected), ()
    )
    ordered_violations = tuple(sorted(violations))
    allowed = not ordered_violations
    return ConfigurationResult(
        configuration_id=request.configuration_id,
        graph_id=graph.graph_id,
        graph_revision=graph.revision,
        graph_digest=index.graph_digest,
        request_digest=request.digest(),
        model_outcome="allowed_by_model" if allowed else "violates_model",
        evidence_status=(
            "observed_configuration"
            if observations
            else ("possible" if allowed else "not_model_permitted")
        ),
        violations=ordered_violations,
        observation_ids=observations,
    )


def validate_configuration(graph: FeatureGraphRevision, request: ConfigurationRequest) -> ConfigurationResult:
    """Compile and evaluate a standalone snapshot without repository caching."""
    return _validate_with_index(graph, request, compile_feature_graph(graph))


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
        snapshot = self.repository.get_revision(request.graph_id, request.graph_revision)
        if snapshot is None:
            raise ValueError("selected graph revision not found")
        index = self.repository.query_index(request.graph_id, request.graph_revision)
        if index is None:
            index = compile_feature_graph(snapshot)
        return _validate_with_index(snapshot, request, index)
