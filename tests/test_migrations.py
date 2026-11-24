import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.main import create_app
from app.preflight import inspect_items
from tests.conftest import ROOT, alembic, login


@pytest.fixture(params=["sqlite", "postgresql"])
def database(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'legacy.db'}"
        return
    server = os.getenv("TEST_POSTGRES_URL")
    if not server:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL integration tests")
    name = "watch_test_" + uuid4().hex
    parent = create_engine(server, isolation_level="AUTOCOMMIT")
    with parent.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    try:
        yield make_url(server).set(database=name).render_as_string(hide_password=False)
    finally:
        with parent.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        parent.dispose()


def test_upgrade_copy_of_original_schema_and_restore(database, tmp_path):
    original = subprocess.run(
        ["git", "show", "30e38bf1248f77bf3ea275e10bd6c6fb2427c78f:main.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    source = tmp_path / "original.py"
    source.write_text(original, encoding="utf-8")
    (tmp_path / "static").mkdir()
    subprocess.run(
        [sys.executable, str(source)],
        env={**os.environ, "DATABASE_URL": database},
        check=True,
        cwd=tmp_path,
    )
    engine = create_engine(database)
    with engine.begin() as db:
        db.execute(
            text("""INSERT INTO items
            (id, added, type, title, year, status, genres, "seasonsDone", "seasonsTotal", note)
            VALUES (:id, :added, 'anime', :title, 2022, 'watching', '["Драма"]', 2, 4, 'Заметка')"""),
            [
                {"id": "old/α", "added": 1660000000000, "title": "Тихий берег"},
                {"id": "same-title", "added": 1660000010000, "title": "тихий берег"},
            ],
        )
    with engine.connect() as connection:
        assert inspect_items(connection) == {"count": 2, "invalid": [], "duplicates": 1}
    engine.dispose()
    alembic(database, "upgrade", "head")
    alembic(database, "upgrade", "head")
    alembic(database, "check")

    with TestClient(
        create_app(Settings(database, environment="local", token="тестовый-ключ"))
    ) as client:
        login(client)
        archive = client.get("/api/export").json()
        assert archive["events"] == []
        assert [item["id"] for item in archive["items"]] == ["old/α", "same-title"]
        original_item = client.get("/api/items/detail", params={"id": "old/α"}).json()["item"]
        assert original_item["added"] == 1660000000000
        assert original_item["note"] == "Заметка" and original_item["seasonsDone"] == 2
        assert original_item["genres"] == ["Драма"]
        assert (
            client.get(
                "/api/items", params={"q": "берег", "genre": "драма", "sort": "progress"}
            ).json()["total"]
            == 2
        )
        restore = {
            "mode": "replace",
            "confirm": True,
            **{k: archive[k] for k in ("version", "items", "events")},
        }
        result = client.post("/api/items/bulk-import", json=restore)
        assert result.is_success, result.text
        assert client.get("/api/export").json()["items"] == archive["items"]

        at = int(datetime.now(UTC).timestamp() * 1000) + 86400000
        added = client.post(
            "/api/items",
            json={
                "title": "Новый релиз",
                "status": "watching",
                "metadata": {
                    "provider": "anilist",
                    "externalId": 41,
                    "nextEpisode": 2,
                    "nextAiring": at,
                },
            },
        )
        assert added.is_success, added.text
        assert client.get("/api/calendar").json()[0]["at"] == at
        assert client.get("/api/dashboard").is_success

        gate = Barrier(2)

        def create(_):
            gate.wait(timeout=10)
            return client.post("/api/items", json={"title": "Премьера"}).status_code

        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(create, range(2))) == [201, 409]


def test_sqlite_migration_serializes_and_rolls_back(tmp_path):
    url = f"sqlite:///{tmp_path / 'interrupted.db'}"
    alembic(url, "upgrade", "0001_legacy")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text("""INSERT INTO items VALUES
            ('x', 10, 'anime', 'Original', 2000, 'plan', '[]', 0, 0, '')""")
        )
        db.exec_driver_sql("""CREATE TRIGGER reject_backfill BEFORE UPDATE ON items
            BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
    with pytest.raises(subprocess.CalledProcessError):
        alembic(url, "upgrade", "head")
    with engine.begin() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0001_legacy"
        assert "updated" not in {row[1] for row in db.exec_driver_sql("PRAGMA table_info(items)")}
        db.exec_driver_sql("DROP TRIGGER reject_backfill")
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(lambda _: alembic(url, "upgrade", "head").returncode, range(2))) == [
            0,
            0,
        ]
    alembic(url, "check")
    engine.dispose()


def test_export_snapshot_includes_items_and_events_from_one_generation(database):
    from sqlalchemy import event

    alembic(database, "upgrade", "head")
    app = create_app(Settings(database, environment="local", token="тестовый-ключ"))
    with TestClient(app) as client:
        login(client)
        item = client.post("/api/items", json={"title": "Snapshot", "status": "plan"}).json()
        engine = app.state.sessions.kw["bind"]
        if engine.dialect.name == "sqlite":
            with engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        fired = False

        def after_statement(_conn, _cursor, statement, *_):
            nonlocal fired
            if "FROM items ORDER BY items.added, items.id" not in statement or fired:
                return
            fired = True
            response = client.post(
                "/api/items/status",
                params={"id": item["id"]},
                json={"status": "watched"},
            )
            assert response.is_success

        with ThreadPoolExecutor(1) as pool:
            # The nested request uses a separate connection and commits before events are read.
            event.listen(engine, "after_cursor_execute", after_statement)
            result = pool.submit(client.get, "/api/export").result(timeout=15)
            event.remove(engine, "after_cursor_execute", after_statement)
        assert fired and result.is_success
        assert result.json()["items"][0]["status"] == "plan"
        assert result.json()["events"] == []
        assert len(client.get("/api/export").json()["events"]) == 1
