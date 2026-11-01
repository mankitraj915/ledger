"""Application factory. Run with: uvicorn app.main:create_app --factory"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import health
from app.auth.router import router as auth_router
from app.auth.security import TokenCodec, build_password_hasher
from app.config import Settings, get_settings
from app.db import build_engine, build_session_factory
from app.errors import NotFound, register_error_handlers
from app.expenses.router import router as expenses_router
from app.groups.router import router as groups_router
from app.observability import configure_logging, install_request_logging

ROUTERS = (health.router, auth_router, groups_router, expenses_router)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = build_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(
        title="Ledger",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.password_hasher = build_password_hasher(settings)
    app.state.token_codec = TokenCodec(
        secret=settings.jwt_secret, ttl=timedelta(minutes=settings.jwt_ttl_minutes)
    )

    register_error_handlers(app)
    install_request_logging(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Idempotent-Replayed", "X-Request-ID"],
        )

    api = APIRouter(prefix="/api")
    for router in ROUTERS:
        api.include_router(router)
    app.include_router(api)

    if settings.static_dir:
        _serve_frontend(app, Path(settings.static_dir))
    return app


def _serve_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the built single-page app from the same origin as the API (no CORS needed)."""
    root = static_dir.resolve()
    index = root / "index.html"
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise NotFound("Not found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)  # client-side routes such as /groups/42
