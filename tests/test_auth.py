import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_production_fails_closed(db_url):
    with pytest.raises(RuntimeError, match="APP_TOKEN"):
        with TestClient(create_app(Settings(db_url))):
            pass
    with pytest.raises(RuntimeError, match="restricted"):
        with TestClient(create_app(Settings(db_url, disable_auth=True))):
            pass


def test_session_csrf_and_logout(client):
    assert client.get("/api/items").status_code == 401
    assert client.get("/api/export").status_code == 401
    assert client.get("/api/health").status_code == 200
    headers = {"X-Watch-Login": "1"}
    credentials = {"token": "тестовый-ключ"}
    assert client.post("/api/auth/login", json=credentials).status_code == 403
    response = client.post("/api/auth/login", headers=headers, json=credentials)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    status = client.get("/api/auth/session")
    assert status.headers["cache-control"] == "no-store"
    csrf = {"X-CSRF-Token": status.json()["csrf"]}
    assert client.post("/api/items", json={"title": "Пример"}).status_code == 403
    assert (
        client.post(
            "/api/items",
            headers={**csrf, "Origin": "https://other.example"},
            json={"title": "Пример"},
        ).status_code
        == 403
    )
    assert client.post("/api/items", headers=csrf, json={"title": "Пример"}).status_code == 201
    assert client.post("/api/auth/logout", headers=csrf).status_code == 200
    assert client.get("/api/items").status_code == 401


def test_throttle_and_redaction(client):
    for _ in range(8):
        assert (
            client.post(
                "/api/auth/login", headers={"X-Watch-Login": "1"}, json={"token": "wrong-token"}
            ).status_code
            == 401
        )
    throttled = client.post(
        "/api/auth/login", headers={"X-Watch-Login": "1"}, json={"token": "wrong-token"}
    )
    assert throttled.status_code == 429 and throttled.headers["Retry-After"]
    assert client.post(
        "/api/auth/login", headers={"X-Watch-Login": "1"}, json={"token": "тестовый-ключ"}
    ).is_success
    invalid = client.post("/api/auth/login", json={"token": ["sentinel-secret"]})
    assert invalid.status_code == 422 and "sentinel-secret" not in invalid.text
    assert client.post("/api/auth/login", content=b"x" * 4097).status_code == 413


def test_production_cookie_and_revoke_all(db_url):
    app = create_app(Settings(db_url, token="test", origin="https://tracker.test"))
    with TestClient(app, base_url="https://tracker.test") as client:
        headers = {"X-Watch-Login": "1", "Origin": "https://tracker.test"}
        response = client.post("/api/auth/login", headers=headers, json={"token": "test"})
        assert "__Host-watch_session=" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        first = client.cookies.get("__Host-watch_session")
        client.cookies.clear()
        assert client.post("/api/auth/login", headers=headers, json={"token": "test"}).is_success
        csrf = client.get("/api/auth/session").json()["csrf"]
        assert client.post("/api/auth/logout-all", headers={"X-CSRF-Token": csrf}).is_success
        client.cookies.set("__Host-watch_session", first)
        assert client.get("/api/items").status_code == 401


def test_unauthorized_import_does_not_read_asgi_body(client):
    from starlette.requests import Request

    async def send(message):
        messages.append(message)

    async def receive():
        raise AssertionError("Unauthorized request body was read")

    messages = []
    scope = {
        "type": "http",
        "app": client.app,
        "method": "POST",
        "path": "/api/items/bulk-import",
        "headers": [],
        "state": {},
    }
    assert Request(scope).method == "POST"
    client.portal.call(client.app, scope, receive, send)
    assert messages[0]["status"] == 401
    assert b"content-security-policy" in dict(messages[0]["headers"])
