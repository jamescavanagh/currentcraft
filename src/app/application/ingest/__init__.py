"""Ingestion application layer: raw topics, adapters, domain records, IngestRing, tensor plans. No bytes, no arrays."""

from .contracts import *  # noqa: F401,F403
from .contracts import CONTRACTS, SCHEMA_VERSION, TENSOR_CONTRACTS  # noqa: F401
from .ports import BlobStorePort, SourceAdapterPort, TensorizerPort  # noqa: F401
from .ring import IngestRing, RingFull  # noqa: F401
from .services import IngestPipeline, TensorService  # noqa: F401
from .workbook import *  # noqa: F401,F403
from .workbook import WORKBOOK_CONTRACTS  # noqa: F401
from .workbook_views import OUTLINE_COLUMNS, wbs_outline  # noqa: F401

CONTRACTS = CONTRACTS + WORKBOOK_CONTRACTS
