import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def alembic(url, *args):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url, "DATABASE_URL_DIRECT": ""},
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'watchlist.db'}"
    alembic(url, "upgrade", "head")
    return url


@pytest.fixture
def client(db_url):
    with TestClient(
        create_app(Settings(db_url, environment="local", token="тестовый-ключ"))
    ) as client:
        yield client


@pytest.fixture
def authorized(client):
    login(client)
    return client


def login(client):
    assert (
        client.post(
            "/api/auth/login", headers={"X-Watch-Login": "1"}, json={"token": "тестовый-ключ"}
        ).status_code
        == 200
    )
    auth = client.get("/api/auth/session")
    assert auth.status_code == 200
    client.headers["X-CSRF-Token"] = auth.json()["csrf"]
