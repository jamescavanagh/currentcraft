"""Numpy-backed plate adapters and kernels. The only place plate arrays exist."""

from .adapters import (NumpyArcBoundAdapter, NumpyPlateDynamicsAdapter, NumpyPlateFieldAdapter,  # noqa: F401
                       put_points)
from .wiring import build_numpy_plate  # noqa: F401
