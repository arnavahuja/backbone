"""FastAPI application factory. The API only validates, delegates and serializes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backbone import __version__
from backbone.api.errors import install_error_handlers
from backbone.api.routers import compare, data, plugins, presets, research, runs, system
from backbone.api.routers import jobs as jobs_router
from backbone.core.config import Settings
from backbone.core.logging import configure_logging
from backbone.services.container import Services
from backbone.services.jobs import JobManager
from backbone.services.run_service import RunService

API_PREFIX: Final = "/api/v1"


def create_app(
    settings: Settings | None = None,
    services: Services | None = None,
    jobs: JobManager | None = None,
) -> FastAPI:
    """Build the application.

    Args:
        settings: Settings (defaults to environment/.env).
        services: Pre-built services (tests).
        jobs: Pre-built job manager (tests).
    """
    settings = settings or (services.settings if services else Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, json=settings.log_json)
        svc = services or Services.create(settings)
        mgr = jobs or JobManager(settings, max_workers=settings.max_workers)
        app.state.services = svc
        app.state.jobs = mgr
        app.state.run_service = RunService(svc, mgr)
        if settings.dev_mode:
            svc.plugins.start_watcher()
        try:
            yield
        finally:
            svc.plugins.stop_watcher()
            if jobs is None:
                mgr.shutdown()

    app = FastAPI(
        title="Backbone API",
        version=__version__,
        description="Local strategy research and backtesting platform.",
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
    )
    origins = {settings.frontend_origin, settings.frontend_origin.replace("127.0.0.1", "localhost")}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    api = APIRouter(prefix=API_PREFIX)
    for module in (system, plugins, data, runs, compare, jobs_router, presets, research):
        api.include_router(module.router)
    app.include_router(api)
    return app
