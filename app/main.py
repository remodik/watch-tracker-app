import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import exc, text

from app.config import Settings
from app.database import make_engine, make_sessions
from app.middleware import SecurityMiddleware
from app.routers import auth, backup, catalog, items, statistics
from app.services.catalog import Catalog

STATIC = Path(__file__).resolve().parents[1] / "static"
logger = logging.getLogger(__name__)


def create_app(settings=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application):
        settings.validate()
        engine = make_engine(settings.database_url)
        try:
            with engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
            if revision != "0002_library":
                raise RuntimeError("Upgrade the database with alembic upgrade head")
            application.state.sessions = make_sessions(engine)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(6.0, connect=3.0),
                limits=httpx.Limits(max_connections=6),
                trust_env=False,
            ) as client:
                application.state.catalog = Catalog(client, settings)
                yield
        except exc.SQLAlchemyError:
            raise RuntimeError(
                "Database unavailable or unmigrated. Run alembic upgrade head."
            ) from None
        finally:
            engine.dispose()

    application = FastAPI(
        title="Watch Tracker",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = settings
    application.state.local_csrf = secrets.token_urlsafe(32)
    application.add_middleware(SecurityMiddleware, production=settings.production)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request, error):
        issues = [
            {"field": ".".join(map(str, issue["loc"])), "message": issue["msg"]}
            for issue in error.errors()
        ]
        return JSONResponse(
            {"detail": {"message": "Проверьте введённые данные", "issues": issues}}, status_code=422
        )

    @application.exception_handler(exc.IntegrityError)
    async def conflict(_request, _error):
        return JSONResponse({"detail": "Конфликт данных. Изменения отменены."}, status_code=409)

    @application.exception_handler(exc.SQLAlchemyError)
    async def database_failure(_request, error):
        logger.error("Database operation failed (%s)", type(error).__name__)
        return JSONResponse({"detail": "Ошибка базы данных. Изменения отменены."}, status_code=503)

    application.include_router(auth.router)
    application.include_router(backup.router)
    application.include_router(items.router)
    application.include_router(catalog.router)
    application.include_router(statistics.router)
    application.mount("/assets", StaticFiles(directory=STATIC, html=False), name="assets")

    @application.get("/api/health")
    def health():
        return {"ok": True}

    @application.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    @application.get("/sw.js")
    def worker():
        return FileResponse(
            STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"}
        )

    @application.get("/{path:path}")
    def index(path: str):
        if path and path.split("/")[0] not in {
            "library",
            "anime",
            "films",
            "watching",
            "planned",
            "watched",
            "favorites",
            "calendar",
            "statistics",
            "settings",
            "item",
        }:
            raise HTTPException(404, "Страница не найдена")
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return application


app = create_app()
