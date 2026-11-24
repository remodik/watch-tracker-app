from datetime import UTC, datetime
from threading import Lock

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import login
from tests.test_library import create


def test_tracking_transitions_individual_episodes_and_statistics(authorized):
    item = create(
        authorized,
        "История",
        status="plan",
        year=2020,
        genres=["Драма", "драма"],
        episodesTotal=4,
        seasonsTotal=2,
        seasons=[{"number": 1, "episodesTotal": 2}, {"number": 2, "episodesTotal": 2}],
        metadata={
            "runtime": 24,
            "originalTitle": "Original Title",
            "alternateTitles": ["Альтернатива"],
        },
    )
    assert authorized.get("/api/items", params={"q": "альтернатива"}).json()["total"] == 1
    params = {"id": item["id"]}

    def status(value):
        return authorized.post("/api/items/status", params=params, json={"status": value})

    assert status("rewatching").status_code == 409
    progress = "/api/items/progress"
    for invalid in (True, 0, 1.0):
        assert authorized.post(progress, params=params, json={"delta": invalid}).status_code == 422
    mark = {"unit": "episode", "season": 1, "episode": 2, "watched": True}
    marked = authorized.post(progress, params=params, json=mark).json()
    assert marked["episodesDone"] == 1 and marked["status"] == "watching"
    assert marked["seasons"][0]["watchedEpisodes"] == [2]
    assert authorized.post(progress, params=params, json=mark).json()["episodesDone"] == 1
    assert authorized.post(progress, params=params, json={"delta": 1}).json()["seasonsDone"] == 1
    assert (
        authorized.post(progress, params=params, json={**mark, "watched": False}).json()[
            "seasonsDone"
        ]
        == 0
    )
    assert status("watched").json()["completed"]
    next_watch = status("rewatching").json()
    assert authorized.get("/api/items", params={"active": "true"}).json()["total"] == 1
    assert next_watch["episodesDone"] == 0 and next_watch["carriedEpisodes"] == 1
    assert status("paused").is_success
    assert status("rewatching").json()["carriedEpisodes"] == 1
    assert authorized.post(progress, params=params, json={"delta": 1}).json()["episodesDone"] == 1
    assert status("watched").json()["rewatches"] == 1
    year = datetime.now(UTC).year
    report = authorized.get("/api/statistics", params={"year": year, "tz": "Europe/Moscow"}).json()
    assert report["genres"] == {"драма": 1}
    assert report["total"] == 1 and report["episodes"] == 2 and report["rewatches"] == 1
    assert report["estimatedMinutes"] == 48 and report["annual"]["episodes"] == 2
    assert report["annual"]["completed"] == 2 and report["annual"]["rewatches"] == 1
    assert report["annual"]["added"] == 1
    assert authorized.get("/api/statistics", params={"tz": "No/Such_Zone"}).status_code == 422
    archive = authorized.get("/api/export").json()
    assert len([event for event in archive["events"] if event["kind"] == "progress"]) == 4
    assert authorized.post(
        "/api/items/bulk-import",
        json={
            "mode": "merge",
            **{key: archive[key] for key in ("version", "items", "events")},
        },
    ).is_success


def test_optional_providers_do_not_block_collection(authorized):
    assert authorized.get("/api/catalog/status").json() == {"anilist": False, "tmdb": False}
    for provider in ("anilist", "tmdb"):
        assert (
            authorized.get(f"/api/catalog/{provider}/search", params={"q": "кино"}).status_code
            == 503
        )
    assert authorized.get("/api/items").is_success
    assert authorized.get("/api/calendar").json() == []


def test_catalog_search_refresh_cache_retries_and_airing(db_url):
    calls = []
    lock = Lock()
    tmdb_failures = 0
    next_airing = int(datetime.now(UTC).timestamp()) + 86400
    anime = {
        "id": 144,
        "title": {"english": "Quiet Sea", "native": "海", "romaji": "Umi"},
        "synonyms": ["Тихое море"],
        "startDate": {"year": 2025, "month": 1, "day": 2},
        "coverImage": {"large": "https://s4.anilist.co/example.jpg"},
        "bannerImage": None,
        "description": "<p>Описание<br>строка</p>",
        "genres": ["Drama"],
        "episodes": 2,
        "duration": 24,
        "status": "RELEASING",
        "averageScore": 81,
        "nextAiringEpisode": {"episode": 2, "airingAt": next_airing},
        "relations": {
            "edges": [
                {
                    "relationType": "SEQUEL",
                    "node": {
                        "id": 145,
                        "type": "ANIME",
                        "title": {"english": "Quiet Sea 2"},
                    },
                }
            ]
        },
    }

    def serve(request):
        nonlocal tmdb_failures
        with lock:
            calls.append(str(request.url))
        if request.url.host == "graphql.anilist.co":
            if b'"q":"limit"' in request.content:
                return httpx.Response(429, headers={"Retry-After": "30"})
            if b'"q":' in request.content:
                return httpx.Response(200, json={"data": {"Page": {"Media": [anime]}}})
            return httpx.Response(200, json={"data": {"Media": anime}})
        assert request.headers["Authorization"] == "Bearer private-read-token"
        if request.url.path.endswith("/configuration"):
            return httpx.Response(
                200,
                json={
                    "images": {
                        "secure_base_url": "https://image.tmdb.org/t/p/",
                        "poster_sizes": ["w342", "original"],
                    }
                },
            )
        if request.url.path.endswith("/movie/77"):
            tmdb_failures += 1
            if tmdb_failures == 1:
                return httpx.Response(502)
            return httpx.Response(
                200,
                json={
                    "id": 77,
                    "title": "Название",
                    "original_title": "Original",
                    "release_date": "2024-01-01",
                    "poster_path": "/poster.png",
                    "runtime": 120,
                    "genres": [{"name": "Драма"}],
                    "vote_count": 3,
                    "vote_average": 7.5,
                },
            )
        return httpx.Response(200, json=[])

    settings = Settings(
        db_url,
        environment="local",
        token="тестовый-ключ",
        anilist=True,
        tmdb_token="private-read-token",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        mock = httpx.AsyncClient(transport=httpx.MockTransport(serve))
        app.state.catalog.client = mock
        try:
            login(client)
            search_path = "/api/catalog/anilist/search"
            for _ in range(2):
                response = client.get(search_path, params={"q": "Тихое море"})
                assert response.json()[0]["metadata"]["externalId"] == 144
            assert calls.count("https://graphql.anilist.co") == 1
            film = client.get("/api/catalog/tmdb/77")
            assert film.json()["metadata"]["runtime"] == 120 and tmdb_failures == 2
            assert film.json()["metadata"]["poster"] == "https://image.tmdb.org/t/p/w342/poster.png"
            assert "private-read-token" not in film.text
            assert client.get("/api/catalog/tmdb/search", params={"q": "кино"}).status_code == 502
            item = create(
                client,
                "Моё название",
                note="Заметка",
                rating=7,
                episodesDone=3,
                status="watching",
                metadata={"provider": "anilist", "externalId": 144},
            )
            refreshed = client.post("/api/catalog/refresh", params={"id": item["id"]}).json()
            assert (
                refreshed["note"],
                refreshed["rating"],
                refreshed["episodesDone"],
                refreshed["episodesTotal"],
            ) == ("Заметка", 7, 3, 3)
            assert refreshed["title"] == "Моё название"
            assert "<p>" not in refreshed["metadata"]["description"]
            assert refreshed["metadata"]["related"][0]["id"] == 145
            airing = client.get("/api/calendar").json()[0]
            assert (airing["source"], airing["at"], airing["episode"]) == (
                "anilist",
                next_airing * 1000,
                2,
            )
            film_entry = create(
                client,
                "Мой фильм",
                type="film",
                rating=9,
                metadata={"provider": "tmdb", "externalId": 77},
            )
            batch = client.post("/api/catalog/refresh-batch", params={"provider": "tmdb"})
            assert batch.json() == {"updated": 1, "failed": 0}
            refreshed_film = client.get(
                "/api/items/detail", params={"id": film_entry["id"]}
            ).json()["item"]
            assert refreshed_film["rating"] == 9 and refreshed_film["metadata"]["runtime"] == 120
            count = len(calls)
            assert client.get(search_path, params={"q": "limit"}).headers["Retry-After"] == "30"
            assert client.get(search_path, params={"q": "different"}).status_code == 429
            assert len(calls) == count + 1
            assert client.get("/api/items").is_success
        finally:
            client.portal.call(mock.aclose)


def test_catalog_optional_fields_and_titles():
    from app.services.catalog import anime_record, film_record

    anime = anime_record(
        {
            "id": 42,
            "title": {"english": "  ", "romaji": "Title"},
            "startDate": None,
            "relations": {"edges": [None, {"node": None}]},
            "nextAiringEpisode": {"airingAt": 1},
            "episodes": "unknown",
        }
    )
    assert anime.title == "Title" and anime.year is None
    assert anime.metadata.related == [] and anime.metadata.nextAiring is None
    film = film_record(
        {
            "id": 7,
            "title": "Film",
            "alternative_titles": {
                "titles": [
                    {"title": "  "},
                    {"title": " Alt "},
                    None,
                    {"title": "alt"},
                    {"title": 7},
                ]
            },
        },
        {},
    )
    assert film.metadata.alternateTitles == ["Alt"]


def test_local_calendar_dates(monkeypatch, authorized):
    from datetime import datetime

    from app import viewing_time

    class Clock(datetime):
        @classmethod
        def now(cls, zone):
            return datetime(2025, 1, 1, 12, 30, tzinfo=UTC).astimezone(zone)

    monkeypatch.setattr(viewing_time, "datetime", Clock)
    for index, (zone, day) in enumerate(
        [
            ("Pacific/Kiritimati", "2025-01-02"),
            ("Etc/GMT+12", "2025-01-01"),
            ("Europe/Moscow", "2025-01-01"),
            ("Asia/Tokyo", "2025-01-01"),
        ]
    ):
        result = authorized.post(
            "/api/items",
            headers={"X-Watch-Timezone": zone},
            json={"title": f"Zone {index}", "status": "plan", "started": day},
        )
        assert result.is_success, result.text
        state = authorized.post(
            "/api/items/status",
            params={"id": result.json()["id"]},
            json={"status": "watched"},
            headers={"X-Watch-Timezone": zone},
        )
        assert state.json()["completed"] == day
    rejected = authorized.post(
        "/api/items",
        headers={"X-Watch-Timezone": "Etc/GMT+12"},
        json={"title": "Future", "started": "2025-01-02"},
    )
    assert rejected.status_code == 422


def test_cancellation_keeps_seen_episodes_without_counting_rewatch(authorized):
    item = create(authorized, "Cancel rewatch", status="watched", episodesDone=2, episodesTotal=5)
    params = {"id": item["id"]}

    def transition(status):
        response = authorized.post("/api/items/status", params=params, json={"status": status})
        assert response.is_success, response.text
        return response.json()

    transition("rewatching")
    authorized.post("/api/items/progress", params=params, json={"delta": 1})
    assert transition("paused")["rewatchInProgress"]
    assert transition("rewatching")["episodesDone"] == 1
    cancelled = transition("plan")
    assert cancelled["rewatches"] == 0 and not cancelled["rewatchInProgress"]
    again = transition("rewatching")
    assert again["carriedEpisodes"] == 3
    state = transition("watched")
    assert state["rewatches"] == 1
    transition("paused")
    assert transition("watched")["rewatches"] == 1
    report = authorized.get("/api/statistics").json()
    assert report["episodes"] == 3
    assert report["annual"]["completed"] == 1
