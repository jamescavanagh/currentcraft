"""Interface-local dependency injection container contract."""

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.application.persistence.ports import UnitOfWorkFactory

from .document_projection import HandleCodec
from .settings import Settings


@dataclass
class Container:
    settings: Settings
    database_ready: Callable[[], Awaitable[bool]]
    broker_ready: Callable[[], Awaitable[bool]]
    close: Callable[[], Awaitable[None]]

    uow_factory: UnitOfWorkFactory | None = None
    handles: HandleCodec = field(default_factory=HandleCodec, repr=False)
