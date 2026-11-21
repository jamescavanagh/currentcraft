"""Synthetic single-process history adapter, not durable or thread-safe storage."""
from uuid import UUID

from app.application.feature_graph import FeatureGraphService
from app.domain.operand.feature_graph import FeatureGraphRevision


class MemoryFeatureGraphRepository:
    def __init__(self):
        self._history: dict[UUID, tuple[FeatureGraphRevision, ...]] = {}

    def history(self, graph_id: UUID) -> tuple[FeatureGraphRevision, ...]:
        return self._history.get(graph_id, ())

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
        self._history[snapshot.graph_id] = history + (snapshot,)


def build_memory_feature_graph() -> tuple[FeatureGraphService, MemoryFeatureGraphRepository]:
    repository = MemoryFeatureGraphRepository()
    return FeatureGraphService(repository), repository
