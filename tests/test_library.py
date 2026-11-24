from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text

from app.database import make_engine


def create(client, title="Фильм", **extra):
    response = client.post("/api/items", json={"title": title, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def library(client):
    response = client.get("/api/items")
    assert response.status_code == 200
    return response.json()["items"]


def test_crud_and_validation(authorized):
    item = create(authorized, " Север ", type="film", year=2024, note="Личная заметка")
    author = authorized
    assert item["title"] == "Север"
    assert (
        author.post("/api/items", json={"title": "север", "type": "film", "year": 2024}).status_code
        == 409
    )
    create(author, "Север", type="film", year=1990)
    create(author, "Север", type="anime", year=2024)
    for payload in [
        {"type": "series"},
        {"status": "whatever"},
        {"year": "2020"},
        {"rating": 11},
        {"seasonsDone": -1},
        {"episodesDone": 3, "episodesTotal": 2},
        {"type": "film", "episodesDone": 2},
        {"note": "x" * 30001},
        {"metadata": {"poster": "javascript:example"}},
        {"metadata": {"externalId": 1}},
        {"started": "2024-02-31"},
        {"unknown": 3},
        {"genres": ["foo"] * 41},
    ]:
        assert author.post("/api/items", json={"title": "Проверка", **payload}).status_code == 422
    params = {"id": item["id"]}
    assert (
        author.put(
            "/api/items/detail",
            params=params,
            json={"title": "Север 2", "type": "film", "rating": 8},
        ).json()["rating"]
        == 8
    )
    assert author.get("/api/items", params={"q": "север 2", "rating_min": 6}).json()["total"] == 1
    assert author.get("/api/items/detail", params=params).json()["item"]["title"] == "Север 2"
    assert author.delete("/api/items/detail", params=params).json()["backupId"]
    assert author.get("/api/items/detail", params=params).status_code == 404


def test_concurrent_create(authorized):
    gate = Barrier(2)

    def request(_):
        gate.wait(timeout=10)
        return authorized.post("/api/items", json={"title": "Одновременно"}).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(request, range(2))) == [201, 409]
    assert len(library(authorized)) == 1


def test_external_identity(authorized):
    create(authorized, "Экран", metadata={"provider": "anilist", "externalId": 10})
    create(authorized, "Экран", metadata={"provider": "anilist", "externalId": 20})
    duplicate = authorized.post(
        "/api/items",
        json={
            "title": "Новое название",
            "metadata": {"provider": "anilist", "externalId": 10},
        },
    )
    assert duplicate.status_code == 409
    assert authorized.post("/api/items", json={"title": "Экран"}).status_code == 409


def test_replace_validates_and_rolls_back_after_delete(authorized, db_url):
    old = create(authorized, "Сохранить")
    path = "/api/items/bulk-import"
    invalid = {"mode": "replace", "confirm": True, "items": [{"title": "Новая"}, {"title": ""}]}
    preview = authorized.post(path + "/preview", json=invalid)
    assert preview.json()["invalid"] == 1
    preview = authorized.post(
        path + "/preview", json={"mode": "merge", "items": [1, {"title": "Готово"}]}
    )
    assert preview.json()["invalid"] == 1 and preview.json()["added"] == 1
    assert (
        authorized.post(path, json={"mode": "merge", "version": True, "items": []}).status_code
        == 422
    )
    assert authorized.post(path, json=invalid).status_code == 422
    engine = make_engine(db_url)
    with engine.begin() as connection:
        connection.execute(
            text("""CREATE TRIGGER fail_insert BEFORE INSERT ON items
            WHEN NEW.title='Проверка отката' BEGIN SELECT RAISE(ABORT, 'rejected'); END""")
        )
    result = authorized.post(
        path,
        json={
            "mode": "replace",
            "confirm": True,
            "items": [
                {"title": "Новая"},
                {"title": "Проверка отката"},
            ],
        },
    )
    assert result.status_code == 409
    assert [item["id"] for item in library(authorized)] == [old["id"]]
    assert not authorized.get("/api/backups").json()["items"]
    engine.dispose()


def test_legacy_import_update_backup_and_restore(authorized):
    path = "/api/items/bulk-import"
    legacy = {
        "id": "old-id",
        "title": "Сериал",
        "added": 12345,
        "type": "anime",
        "status": "watching",
        "seasonsDone": "2",
        "seasonsTotal": 4,
        "note": "Заметка",
    }
    assert authorized.post(path, json={"mode": "merge", "items": [legacy]}).json()["added"] == 1
    assert (
        authorized.post(path, json={"mode": "merge", "items": [legacy]}).json()["duplicates"] == 1
    )
    params = {"id": "old-id"}
    assert (
        authorized.post("/api/items/favorite", params=params, json={"favorite": True}).status_code
        == 200
    )
    result = authorized.post(
        path, json={"mode": "update", "items": [{**legacy, "note": "Новая заметка"}]}
    )
    assert result.json()["updated"] == 1
    assert (
        authorized.post("/api/items/progress", params=params, json={"unit": "season"}).status_code
        == 200
    )
    archive = authorized.get("/api/export").json()
    assert archive["items"][0]["favorite"] is True
    assert archive["items"][0]["added"] == 12345
    assert archive["items"][0]["seasonsDone"] == 3
    assert archive["items"][0]["note"] == "Новая заметка"
    assert len(archive["events"]) == 1
    assert authorized.post(path, json={"items": [], "mode": "replace"}).status_code == 409
    replaced = authorized.post(path, json={"items": [], "mode": "replace", "confirm": True})
    backup = authorized.get(f"/api/backups/{replaced.json()['backupId']}").json()
    assert not library(authorized)
    restore = {
        "mode": "replace",
        "confirm": True,
        **{key: backup[key] for key in ("version", "items", "events")},
    }
    assert authorized.post(path, json=restore).status_code == 200
    assert authorized.get("/api/export").json()["events"] == archive["events"]
    assert [
        {k: v for k, v in item.items() if k != "revision"} for item in library(authorized)
    ] == archive["items"]


def test_conflicting_edit_preserves_concurrent_progress(authorized):
    item = create(authorized, "Сезон", episodesTotal=10)
    params = {"id": item["id"]}
    initial = item["revision"]
    assert authorized.post(
        "/api/items/progress", params=params, json={"unit": "episode"}
    ).is_success
    result = authorized.put(
        "/api/items/detail",
        params={**params, "expected": initial},
        json={"title": "Сезон", "note": "Новая заметка", "episodesTotal": 10},
    )
    assert result.status_code == 409
    assert authorized.get("/api/items/detail", params=params).json()["item"]["episodesDone"] == 1


@pytest.mark.parametrize("mode", ["merge", "update", "replace"])
@pytest.mark.parametrize("updated", [0, None, 253402300799999])
def test_import_cannot_reuse_edit_revision(authorized, mode, updated):
    item = create(authorized, "Import revision")
    archive = authorized.get("/api/export").json()
    archive["items"][0]["updated"] = item["updated"] if updated is None else updated
    imported = authorized.post(
        "/api/items/bulk-import",
        json={"version": 2, "mode": mode, "confirm": True, "items": archive["items"]},
    )
    assert imported.is_success, imported.text
    fresh = authorized.get("/api/items/detail", params={"id": item["id"]}).json()["item"]
    assert (fresh["revision"] == item["revision"]) == (mode == "merge")
    if mode != "merge":
        result = authorized.put(
            "/api/items/detail",
            params={"id": item["id"], "expected": item["revision"]},
            json={"title": "Stale edit"},
        )
        assert result.status_code == 409


def test_missing_library_lock_rejects_write(authorized, db_url):
    with make_engine(db_url).begin() as db:
        db.execute(text("DELETE FROM library_lock"))
    assert authorized.post("/api/items", json={"title": "Rejected"}).status_code == 503
    assert not library(authorized)


def test_progress_409_leaves_nested_tracking_intact(authorized):
    item = create(
        authorized,
        "Episode limit",
        episodesDone=1,
        episodesTotal=1,
        seasons=[{"number": 1, "episodesDone": 1, "episodesTotal": 2, "watchedEpisodes": [1]}],
    )
    params = {"id": item["id"]}
    result = authorized.post(
        "/api/items/progress",
        params=params,
        json={"unit": "episode", "season": 1, "delta": 1},
    )
    assert result.status_code == 409
    assert authorized.get("/api/items/detail", params=params).json() == {"item": item, "events": []}


@pytest.mark.parametrize("status", ["plan", "watching", "paused", "dropped"])
def test_api_disallows_forged_rewatch(authorized, status):
    response = authorized.post(
        "/api/items",
        json={"title": "Invalid rewatch", "status": "rewatching"},
    )
    assert response.status_code == 409
    item = create(authorized, "Valid entry", status=status)
    assert (
        authorized.put(
            "/api/items/detail",
            params={"id": item["id"]},
            json={"title": item["title"], "status": "watched", "rewatches": 4},
        ).status_code
        == 409
    )


def test_server_restore_rejects_stale_preview_and_preserves_event_ids(authorized):
    item = create(authorized, "Server snapshot", episodesTotal=5)
    params = {"id": item["id"]}
    authorized.post("/api/items/progress", params=params, json={"delta": 1})
    archive = authorized.get("/api/export").json()
    snapshot = authorized.post("/api/backups").json()
    path = "/api/backups/" + snapshot["id"]
    preview = authorized.get(path + "/restore-preview").json()
    authorized.post("/api/items/favorite", params=params, json={"favorite": True})
    assert (
        authorized.post(
            path + "/restore", json={"preview": preview["preview"], "confirm": True}
        ).status_code
        == 409
    )
    preview = authorized.get(path + "/restore-preview").json()
    assert authorized.post(
        path + "/restore", json={"preview": preview["preview"], "confirm": True}
    ).is_success
    restored = authorized.get("/api/export").json()
    assert restored["items"] == archive["items"]
    assert restored["events"] == archive["events"]
    assert authorized.get("/api/backups").json()["total_bytes"] > 0
    assert authorized.delete(path).is_success


def test_backup_retention_keeps_manual_and_latest_and_detects_corruption(authorized, db_url):
    from dataclasses import replace

    app = authorized.app
    app.state.sessions.configure(
        info={"settings": replace(app.state.settings, backup_max_automatic_count=1)}
    )
    manual = authorized.post("/api/backups").json()["id"]
    first = create(authorized, "First removal")
    second = create(authorized, "Second removal")
    assert authorized.delete("/api/items/detail", params={"id": first["id"]}).is_success
    removed = authorized.delete("/api/items/detail", params={"id": second["id"]}).json()
    listed = authorized.get("/api/backups").json()["items"]
    assert {row["id"] for row in listed} == {manual, removed["backupId"]}
    engine = make_engine(db_url)
    with engine.begin() as db:
        db.execute(text("UPDATE backups SET archive = '{}' WHERE id = :id"), {"id": manual})
    engine.dispose()
    assert authorized.get(f"/api/backups/{manual}/restore-preview").status_code == 422
    assert not library(authorized)
