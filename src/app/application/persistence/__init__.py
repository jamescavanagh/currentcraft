"""Persistence application layer: repository ports, unit of work, contracts and use cases. No drivers or SQL."""

from .contracts import *  # noqa: F401,F403
from .contracts import CONTRACTS, SCHEMA_VERSION, InsufficientStock, VersionConflict  # noqa: F401
from .ports import (AggregateRepository, CommandLog, EmbeddingRepository, GraphRepository, OutboxRepository,  # noqa: F401
                    SourceObjectRepository, StockRepository, UnitOfWork, UnitOfWorkFactory)
from .services import (documents_for, load_aggregate, persist_objects, relay_outbox, reserve_stock, run_once,  # noqa: F401
                       save_aggregate, tasks_of)

TENSOR_CONTRACTS = ()
