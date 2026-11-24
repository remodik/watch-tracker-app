from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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
    assert library(authorized) == archive["items"]


def test_conflicting_edit_preserves_concurrent_progress(authorized):
    item = create(authorized, "Сезон", episodesTotal=10)
    params = {"id": item["id"]}
    initial = item["updated"]
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
