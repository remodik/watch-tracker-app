import hashlib
import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import exc

from app.config import Settings
from app.database import make_engine, make_sessions
from app.middleware import SecurityMiddleware
from app.models import LibraryLock, LoginLock
from app.routers import auth, backup, catalog, items, statistics
from app.services.catalog import Catalog

STATIC = Path(__file__).resolve().parents[1] / "static"
logger = logging.getLogger(__name__)


def static_release(static_dir):
    paths = sorted(path for path in static_dir.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(static_dir).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    version = digest.hexdigest()[:24]
    prefix = f"/assets/{version}/"
    assets = [
        prefix + path.relative_to(static_dir).as_posix()
        for path in paths
        if path.suffix.lower() in {".css", ".js", ".svg", ".png", ".webp", ".woff2"}
        and path.name != "sw.js"
    ]
    assets.append(prefix + "offline.html")
    worker = (static_dir / "sw.js").read_text().replace("__WATCH_RELEASE__", version)
    worker = worker.replace("/* RELEASE_ASSETS */ []", json.dumps(assets))
    return prefix, worker


def versioned_html(static_dir, name, prefix):
    return (static_dir / name).read_text().replace('"/assets/', f'"{prefix}')


def create_app(settings=None, *, static_dir=STATIC):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application):
        settings.validate()
        engine = make_engine(settings.database_url)
        try:
            config = Config()
            config.set_main_option("script_location", str(STATIC.parent / "migrations"))
            heads = set(ScriptDirectory.from_config(config).get_heads())
            try:
                with engine.connect() as connection:
                    revisions = set(MigrationContext.configure(connection).get_current_heads())
                    if revisions != heads:
                        raise RuntimeError("Upgrade the database with alembic upgrade head")
                    for lock in (LibraryLock, LoginLock):
                        if not connection.execute(
                            lock.__table__.select().where(lock.id == 1)
                        ).first():
                            raise RuntimeError("Required database lock row is missing")
            except exc.SQLAlchemyError:
                raise RuntimeError("Database unavailable during startup checks") from None
            application.state.sessions = make_sessions(engine, settings)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(6.0, connect=3.0),
                limits=httpx.Limits(max_connections=6),
                trust_env=False,
            ) as client:
                application.state.catalog = Catalog(client, settings)
                yield
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
    prefix, release_worker = static_release(static_dir)
    index_html = versioned_html(static_dir, "index.html", prefix)
    offline_html = versioned_html(static_dir, "offline.html", prefix)

    @application.get(prefix + "offline.html")
    def offline():
        return HTMLResponse(offline_html)

    application.mount(
        prefix.rstrip("/"), StaticFiles(directory=static_dir, html=False), name="release-assets"
    )
    application.mount("/assets", StaticFiles(directory=static_dir, html=False), name="assets")

    @application.get("/api/health")
    def health():
        return {"ok": True}

    @application.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(
            static_dir / "manifest.webmanifest", media_type="application/manifest+json"
        )

    @application.get("/sw.js")
    def worker():
        return Response(
            release_worker, media_type="text/javascript", headers={"Cache-Control": "no-cache"}
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
        return HTMLResponse(index_html, headers={"Cache-Control": "no-cache"})

    return application


app = create_app()
