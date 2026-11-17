"""Numpy-backed gauge adapters. The only place gauge arrays exist."""

from .numpy_adapters import (NumpyGaugeInvarianceAdapter, NumpyGaugeReductionAdapter,  # noqa: F401
                             NumpyParticipationNullAdapter, put_embeddings)
from .wiring import build_numpy_gauge  # noqa: F401
from .geodesic import build_numpy_geodesic_probe  # noqa: F401

from .winding import NumpyVelocityWindingAdapter, put_velocity_winding_inputs, measure_velocity_winding  # noqa: F401
