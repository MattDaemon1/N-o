"""FastAPI application entrypoint for NÉO (local-only 127.0.0.1:7860)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import (
    routes_audio,
    routes_dashboard,
    routes_models,
    routes_session,
    routes_settings,
    routes_tts,
)
from app.config.defaults import APP_VERSION, DEFAULT_HOST, DEFAULT_PORT
from app.runtime import NeoRuntime


def create_app(config_path: Path | str = "dashboard_config.json") -> FastAPI:
    runtime = NeoRuntime(config_path=config_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.startup()
        try:
            yield
        finally:
            await runtime.shutdown()

    app = FastAPI(
        title="NÉO — Assistant formateur IA local",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    app.state.runtime = runtime

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(routes_dashboard.router)
    app.include_router(routes_session.router)
    app.include_router(routes_audio.router)
    app.include_router(routes_models.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_tts.router)

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        reload=False,
        log_level="info",
    )
