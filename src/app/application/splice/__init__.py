"""Sparse phase splice: workbook source occurrences -> phase-blocked sparse embeddings with declared phase parameters."""

from .contracts import *  # noqa: F401,F403
from .contracts import CONTRACTS, SCHEMA_VERSION, TOKENIZER  # noqa: F401
from .ports import SpliceKernelPort  # noqa: F401
from .services import SpliceService, assign_phases, store_splice  # noqa: F401
