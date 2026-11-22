"""Synthetic single-process history adapter, not durable or thread-safe storage."""
from uuid import UUID

from app.application.feature_graph import FeatureGraphService
from app.application.feature_graph.query_index import FeatureGraphQueryIndex, compile_feature_graph
from app.domain.operand.feature_graph import FeatureGraphRevision


class MemoryFeatureGraphRepository:
    def __init__(self):
        self._history: dict[UUID, tuple[FeatureGraphRevision, ...]] = {}
        self._by_revision: dict[tuple[UUID, int], FeatureGraphRevision] = {}
        self._query_indexes: dict[tuple[UUID, int], FeatureGraphQueryIndex] = {}

    def history(self, graph_id: UUID) -> tuple[FeatureGraphRevision, ...]:
        return self._history.get(graph_id, ())

    def get_revision(self, graph_id: UUID, revision: int) -> FeatureGraphRevision | None:
        return self._by_revision.get((graph_id, revision))

    def query_index(self, graph_id: UUID, revision: int) -> FeatureGraphQueryIndex | None:
        return self._query_indexes.get((graph_id, revision))

    def append(self, snapshot: FeatureGraphRevision, *, expected_revision: int) -> None:
        history = self.history(snapshot.graph_id)
        for prior in history:
            if prior.revision == snapshot.revision:
                if prior == snapshot and expected_revision == snapshot.revision - 1:
                    return
                raise ValueError("immutable graph revision conflict")
        current = history[-1].revision if history else 0
        if expected_revision != current or snapshot.revision != current + 1:
            raise ValueError("graph revision compare-and-swap conflict")
        if history and snapshot.recorded_at < history[-1].recorded_at:
            raise ValueError("recorded time cannot go backwards")
        known = {}
        for prior in history:
            for feature in prior.features:
                known[feature.feature_id] = feature
        for feature in snapshot.features:
            previous = known.get(feature.feature_id)
            if previous is not None and (feature.version < previous.version or
                                          (feature.version == previous.version and feature != previous)):
                raise ValueError("feature definition version is immutable and cannot regress")
        index = compile_feature_graph(snapshot)
        key = (snapshot.graph_id, snapshot.revision)
        self._history[snapshot.graph_id] = history + (snapshot,)
        self._by_revision[key] = snapshot
        self._query_indexes[key] = index


def build_memory_feature_graph() -> tuple[FeatureGraphService, MemoryFeatureGraphRepository]:
    repository = MemoryFeatureGraphRepository()
    return FeatureGraphService(repository), repository
