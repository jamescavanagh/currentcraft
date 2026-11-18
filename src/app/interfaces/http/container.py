"""Interface-local dependency injection container contract."""

from dataclasses import dataclass
from typing import Awaitable, Callable

from .settings import Settings


@dataclass
class Container:
    settings: Settings
    database_ready: Callable[[], Awaitable[bool]]
    broker_ready: Callable[[], Awaitable[bool]]
    close: Callable[[], Awaitable[None]]
