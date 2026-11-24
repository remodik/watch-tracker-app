import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import BigInteger, cast, func, select
from starlette.concurrency import run_in_threadpool

from app.database import lock_library
from app.dependencies import require_user
from app.identity import decode_genres, genre_key, search_key
from app.models import Item
from app.schemas import ExternalId, Identifier, Provider
from app.services.catalog import TMDB, bounded_int, optional_list, optional_object, title_string
from app.services.library import get_item, item_response, now_ms, touch_item, tracking

router = APIRouter(prefix="/api/catalog", dependencies=[Depends(require_user)])


@router.get("/status")
def status(request: Request):
    return request.app.state.catalog.enabled()


@router.get("/watch/search")
async def watch_search(
    request: Request,
    kind: Literal["movie", "tv"],
    q: Annotated[str, Query(min_length=2, max_length=150)],
):
    catalog = request.app.state.catalog
    if not catalog.enabled()["tmdb"]:
        raise HTTPException(503, "Интеграция с TMDB отключена")
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(422, "Введите не менее двух символов")
    result = await catalog.fetch(
        "tmdb",
        "GET",
        f"{TMDB}/search/{kind}",
        params={"query": q, "language": "ru-RU", "include_adult": "false"},
    )
    candidates = []
    for row in optional_list(result.get("results"))[:12]:
        row = optional_object(row)
        name = title_string(row.get("title") or row.get("name"))
        candidate_id = bounded_int(row.get("id"), 1, 2_147_483_647)
        if candidate_id and name:
            released = row.get("release_date") or row.get("first_air_date")
            candidates.append(
                {
                    "id": candidate_id,
                    "title": name,
                    "originalTitle": title_string(
                        row.get("original_title") or row.get("original_name")
                    ),
                    "year": released[:4]
                    if isinstance(released, str) and released[:4].isdigit()
                    else None,
                }
            )
    return candidates


@router.get("/watch/{kind}/{catalog_id}")
async def watch_providers(
    request: Request,
    kind: Literal["movie", "tv"],
    catalog_id: ExternalId,
    region: Annotated[str, Query(pattern=r"^[A-Z]{2}$")],
):
    catalog = request.app.state.catalog
    if not catalog.enabled()["tmdb"]:
        raise HTTPException(503, "Интеграция с TMDB отключена")
    result = await catalog.fetch("tmdb", "GET", f"{TMDB}/{kind}/{catalog_id}/watch/providers")
    offers = optional_object(optional_object(result.get("results")).get(region))
    return {
        category: list(
            dict.fromkeys(
                name
                for provider in optional_list(offers.get(category))[:50]
                if (name := title_string(optional_object(provider).get("provider_name")))
            )
        )
        for category in ("flatrate", "rent", "buy", "free", "ads")
    }


@router.get("/{provider}/search")
async def search(
    provider: Provider, request: Request, q: Annotated[str, Query(min_length=2, max_length=150)]
):
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(422, "Введите не менее двух символов")
    return await request.app.state.catalog.lookup(provider, query=q)


@router.get("/{provider}/{catalog_id}")
async def detail(provider: Provider, catalog_id: ExternalId, request: Request):
    return await request.app.state.catalog.lookup(provider, catalog_id=catalog_id)


def get_source(sessions, item_id):
    with sessions() as db:
        item = get_item(db, item_id)
        provider, catalog_id = (
            item.metadata_json.get("provider"),
            item.metadata_json.get("externalId"),
        )
        if not provider or not catalog_id:
            raise HTTPException(409, "У произведения нет идентификатора каталога")
        return provider, catalog_id


def refresh(sessions, item_id, provider, catalog_id, catalog_item):
    with sessions() as db:
        lock_library(db)
        item = get_item(db, item_id)
        if (item.metadata_json.get("provider"), item.metadata_json.get("externalId")) != (
            provider,
            catalog_id,
        ):
            raise HTTPException(409, "Источник изменился. Повторите обновление.")
        new_metadata = catalog_item.metadata.model_dump(exclude_none=True)
        item.metadata_json = {
            **item.metadata_json,
            **new_metadata,
            "nextEpisode": new_metadata.get("nextEpisode"),
            "nextAiring": new_metadata.get("nextAiring"),
        }
        state = tracking(item)
        if catalog_item.episodesTotal and not state["episodesTotalFromSeasons"]:
            state["episodesTotal"] = max(
                catalog_item.episodesTotal,
                state["episodesDone"],
                sum(s["episodesTotal"] for s in state["seasons"]),
            )
        item.tracking = state
        genres = decode_genres(item.genres_json)
        if not genres and catalog_item.genres:
            genres = catalog_item.genres
            item.genres_json = json.dumps(genres, ensure_ascii=False)
            item.genre_search = genre_key(genres)
        item.search_text = search_key(item.title, genres, item.note, item.year, item.metadata_json)
        touch_item(item)
        db.commit()
        return item_response(item)


@router.post("/refresh")
async def refresh_item(id: Identifier, request: Request):
    sessions = request.app.state.sessions
    provider, catalog_id = await run_in_threadpool(get_source, sessions, id)
    data = await request.app.state.catalog.lookup(provider, catalog_id=catalog_id)
    return await run_in_threadpool(refresh, sessions, id, provider, catalog_id, data)


def due_for_refresh(sessions, provider):
    with sessions() as db:
        fetched = func.coalesce(cast(Item.metadata_json["fetchedAt"].as_string(), BigInteger), 0)
        return db.execute(
            select(Item.id, Item.metadata_json["externalId"].as_integer())
            .where(
                Item.metadata_json["provider"].as_string() == provider,
                Item.status.in_(["watching", "rewatching", "paused", "plan"])
                if provider == "anilist"
                else Item.type == ("anime" if provider == "shikimori" else "film"),
                fetched < now_ms() - 45 * 60 * 1000,
            )
            .order_by(fetched, Item.id)
            .limit(6)
        ).all()


@router.post("/refresh-batch")
async def refresh_batch(provider: Provider, request: Request):
    catalog = request.app.state.catalog
    if not catalog.enabled()[provider]:
        raise HTTPException(503, "Интеграция с каталогом отключена")
    sessions = request.app.state.sessions
    entries = await run_in_threadpool(due_for_refresh, sessions, provider)
    updated = failed = 0
    for item_id, catalog_id in entries:
        try:
            data = await catalog.lookup(provider, catalog_id=catalog_id)
            await run_in_threadpool(refresh, sessions, item_id, provider, catalog_id, data)
            updated += 1
        except HTTPException as exc:
            if exc.status_code == 429 and not updated:
                raise
            failed += 1
            if exc.status_code == 429:
                break
    return {"updated": updated, "failed": failed}
