"""FastAPI application wiring."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request as FastApiRequest
from starlette.responses import JSONResponse, Response

from .hijack import HijackHandler
from .litellm_client import LiteLLMClient
from .proxy import UpstreamProxy
from .settings import Settings
from .stats import StatsRegistry

logger = logging.getLogger(__name__)


def _build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        proxy = UpstreamProxy(settings.upstream_base_url)
        llm = LiteLLMClient(settings)
        stats = StatsRegistry()
        app.state.settings = settings
        app.state.proxy = proxy
        app.state.llm = llm
        app.state.stats = stats
        app.state.hijack = HijackHandler(settings, proxy, llm, stats)
        logger.info(
            "harp ready: mode=%s upstream=%s litellm=%s",
            settings.mode,
            settings.upstream_base_url,
            settings.litellm_base_url,
        )
        try:
            yield
        finally:
            await proxy.aclose()
            await llm.aclose()

    app = FastAPI(title="harp", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:  # pragma: no cover - trivial
        return JSONResponse(
            {
                "ok": True,
                "mode": settings.mode.value,
                "upstream": settings.upstream_base_url,
            }
        )

    @app.get("/stats")
    async def stats() -> JSONResponse:
        return JSONResponse(app.state.stats.snapshot().to_dict())

    @app.post("/ai/multi-agent")
    async def multi_agent(request: FastApiRequest) -> Response:
        return await app.state.hijack.handle(request)

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def catch_all(path: str, request: FastApiRequest) -> Response:
        return await app.state.proxy.forward(request)

    return app


# Module-level app instance for ``uvicorn harp.server:app``.
app = _build_app()
