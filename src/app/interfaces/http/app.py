"""Lifespan-managed FastAPI application factory."""

from contextlib import asynccontextmanager
from typing import Awaitable, Callable

from fastapi import FastAPI

from app._version import __version__
from .container import Container
from .errors import install_error_handlers
from .routes import auth, health

ContainerFactory = Callable[[], Awaitable[Container]]


def create_app(
    container_factory: ContainerFactory | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if container_factory is None:
            from .settings import Settings
            from .wiring import build_container

            container = await build_container(Settings.from_env())
        else:
            container = await container_factory()

        app.state.container = container
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(
        title="Currentcraft API",
        version=__version__,
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/v1")
    return app
