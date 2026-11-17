"""Gauge application layer (operand gauges from reduced embeddings). Pydantic only; arrays live in infrastructure."""

from .contracts import *  # noqa: F401,F403
from .contracts import CONTRACTS, INPUT_TENSORS, NODE_GAUGE_FEATURES, NODE_GAUGE_MEANINGS, SCHEMA_VERSION, TENSOR_CONTRACTS  # noqa: F401
from .ports import GaugeInvariancePort, GaugeReductionPort, ParticipationNullPort  # noqa: F401
from .services import GaugeService, gauge_nodes_from_interactions  # noqa: F401
from .geodesic import GeodesicProbeRequest, GeodesicProbeResult, GeodesicProbePort, GeodesicProbeService  # noqa: F401

from .winding import VelocityWindingRequest, VelocityWindingResult, VelocityWindingPort  # noqa: F401
