import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Float, case, cast, func, literal, select

from app.identity import decode_genres, fingerprint, genre_key, match_key, normalize, search_key
from app.models import Item, WatchEvent
from app.schemas import EventData, Season


def now_ms():
    return time.time_ns() // 1_000_000


def uuid():
    return str(uuid4())


def tracking(item):
    return {
        "episodesDone": 0,
        "episodesTotal": 0,
        "seasons": [],
        "started": None,
        "completed": None,
        "rewatches": 0,
        "rewatchInProgress": False,
        "carriedEpisodes": 0,
        **item.tracking,
    }


def archive_item(item):
    return {
        "id": item.id,
        "added": item.added,
        "updated": item.updated,
        "title": item.title,
        "type": item.type,
        "year": item.year,
        "status": item.status,
        "genres": decode_genres(item.genres_json),
        "seasonsDone": item.seasons_done,
        "seasonsTotal": item.seasons_total,
        "note": item.note,
        "favorite": item.favorite,
        "rating": item.rating,
        **({"legacyDuplicate": True} if item.identity_key is None else {}),
        "metadata": {
            **{"alternateTitles": [], "description": "", "related": []},
            **{key: value for key, value in item.metadata_json.items() if value is not None},
        },
        **tracking(item),
    }


def archive_event(event):
    return {
        "id": event.id,
        "item_id": event.item_id,
        "at": event.at,
        "kind": event.kind,
        "data": event.data,
    }


def external_identity(metadata):
    if metadata.get("provider"):
        return fingerprint(metadata["provider"], metadata["externalId"])
    return None


def identity(data):
    match = match_key(data.title, data.type, data.year)
    external = external_identity(data.metadata.model_dump())
    return match, external


def duplicate(db, data, excluding=None):
    match, external = identity(data)
    predicates = Item.match_key == match
    if external:
        predicates |= Item.identity_key == external
    candidates = db.scalars(select(Item).where(predicates).order_by(Item.added, Item.id))
    for item in candidates:
        if item.id == excluding:
            continue
        other_external = external_identity(item.metadata_json)
        if (external and external == other_external) or (
            item.match_key == match and (not external or not other_external)
        ):
            return item
    return None


def get_item(db, item_id):
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Запись не найдена")
    return item


def assign(item, data, timestamp):
    item.title, item.type, item.year, item.status = data.title, data.type, data.year, data.status
    item.genres_json = json.dumps(data.genres, ensure_ascii=False)
    item.seasons_done, item.seasons_total = data.seasonsDone, data.seasonsTotal
    item.note, item.favorite, item.rating = data.note, data.favorite, data.rating
    item.metadata_json = data.metadata.model_dump(exclude_none=True)
    item.tracking = data.model_dump(
        include={
            "episodesDone",
            "episodesTotal",
            "seasons",
            "started",
            "completed",
            "rewatches",
            "rewatchInProgress",
            "carriedEpisodes",
        }
    )
    item.match_key, external = identity(data)
    item.identity_key = external or item.match_key
    item.search_text = search_key(item.title, data.genres, item.note, item.year, item.metadata_json)
    item.genre_search = genre_key(data.genres)
    item.updated = timestamp


def add_item(db, data, imported=False):
    timestamp = now_ms()
    item = Item(
        id=(data.id if imported else None) or uuid(),
        added=data.added if imported and data.added is not None else timestamp,
    )
    assign(item, data, data.updated if imported and data.updated is not None else item.added)
    db.add(item)
    return item


def today():
    return datetime.now(UTC).date().isoformat()


def record(db, item, kind, **data):
    db.add(
        WatchEvent(
            id=uuid(),
            item_id=item.id,
            at=now_ms(),
            kind=kind,
            data=EventData(runtime=item.metadata_json.get("runtime"), **data).model_dump(
                exclude_defaults=True
            ),
        )
    )


def set_status(db, item, status):
    previous = item.status
    if status == previous:
        return
    state = tracking(item)
    rewatch = status == "watched" and state["rewatchInProgress"]
    if status == "rewatching" and not state["rewatchInProgress"]:
        if previous != "watched" and not state["completed"] and not state["rewatches"]:
            raise HTTPException(409, "Сначала отметьте произведение просмотренным")
        state["rewatchInProgress"] = True
        state["carriedEpisodes"] = min(
            1_000_000_000, state["carriedEpisodes"] + state["episodesDone"]
        )
        state["episodesDone"] = 0
        item.seasons_done = 0
        state["seasons"] = [
            {**season, "episodesDone": 0, "watchedEpisodes": []} for season in state["seasons"]
        ]
        state["started"], state["completed"] = today(), None
    elif status == "watching" and state["started"] is None:
        state["started"] = today()
    if rewatch:
        state["rewatchInProgress"] = False
        if state["rewatches"] >= 9999:
            raise HTTPException(409, "Достигнут предел повторных просмотров")
        state["rewatches"] += 1
    if status == "watched":
        state["completed"] = today()
    item.status, item.tracking, item.updated = status, state, max(item.updated + 1, now_ms())
    record(
        db,
        item,
        "status",
        status=status,
        rewatch=rewatch,
        film=item.type == "film" and status == "watched",
    )


def update_item(db, item, data):
    previous = tracking(item)
    previous_status = item.status
    season_delta = data.seasonsDone - item.seasons_done
    episode_delta = data.episodesDone - previous["episodesDone"]
    old_identity, old_match = item.identity_key, item.match_key
    assign(item, data, max(item.updated + 1, now_ms()))
    if item.match_key == old_match and not data.metadata.externalId and old_identity is None:
        item.identity_key = None
    if data.status != previous_status:
        item.status = previous_status
        set_status(db, item, data.status)
        if data.status != "rewatching":
            item.tracking = {
                **item.tracking,
                **{k: getattr(data, k) for k in ("started", "completed") if getattr(data, k)},
            }
    if (season_delta or episode_delta) and data.status != "rewatching":
        record(db, item, "progress", episodes=episode_delta, seasons=season_delta)


def change_progress(db, item, payload):
    if item.type != "anime":
        raise HTTPException(409, "Для фильма измените статус просмотра")
    state = tracking(item)
    unit = (
        payload.unit
        if payload.unit != "auto"
        else (
            "episode"
            if state["episodesTotal"] or state["episodesDone"] or state["seasons"]
            else "season"
        )
    )
    season_delta = episode_delta = 0
    if unit == "season":
        next_value = item.seasons_done + payload.delta
        if not 0 <= next_value <= (item.seasons_total or 999):
            raise HTTPException(409, "Достигнута граница прогресса")
        item.seasons_done = next_value
        season_delta = payload.delta
    else:
        episode_delta = payload.delta
        if payload.season is not None or state["seasons"]:
            number = payload.season
            if number is None:
                candidates = state["seasons"] if payload.delta > 0 else reversed(state["seasons"])
                number = next(
                    (
                        s["number"]
                        for s in candidates
                        if (
                            (not s["episodesTotal"] or s["episodesDone"] < s["episodesTotal"])
                            if payload.delta > 0
                            else s["episodesDone"] > 0
                        )
                    ),
                    None,
                )
                if number is None:
                    raise HTTPException(409, "Достигнута граница прогресса")
            if item.seasons_total and number > item.seasons_total:
                raise HTTPException(409, "Сезон отсутствует")
            season = next((s for s in state["seasons"] if s["number"] == number), None)
            if season is None:
                season = Season(number=number).model_dump()
                state["seasons"] = sorted([*state["seasons"], season], key=lambda s: s["number"])
            total, done = season["episodesTotal"], season["episodesDone"]
            was_complete = bool(total and done == total)
            marked = season["watchedEpisodes"] or list(range(1, done + 1))
            if payload.episode is not None:
                if total and payload.episode > total:
                    raise HTTPException(409, "Эпизод отсутствует")
                if payload.watched == (payload.episode in marked):
                    return
                if payload.watched:
                    marked.append(payload.episode)
                else:
                    marked.remove(payload.episode)
                episode_delta = 1 if payload.watched else -1
            elif payload.delta > 0:
                candidates = set(marked)
                next_episode = next(
                    (i for i in range(1, (total or 100000) + 1) if i not in candidates), None
                )
                if next_episode is None:
                    raise HTTPException(409, "Достигнута граница прогресса")
                marked.append(next_episode)
            elif marked:
                marked.remove(max(marked))
            if not 0 <= done + episode_delta <= (total or 100000) or len(marked) > 5000:
                raise HTTPException(409, "Достигнута граница прогресса")
            season["watchedEpisodes"], season["episodesDone"] = sorted(marked), done + episode_delta
            season_delta = int(bool(total and season["episodesDone"] == total)) - int(was_complete)
            if season_delta:
                item.seasons_done = min(
                    item.seasons_total or 999, max(0, item.seasons_done + season_delta)
                )
        new_total = state["episodesDone"] + episode_delta
        if not 0 <= new_total <= (state["episodesTotal"] or 100000):
            raise HTTPException(409, "Достигнута граница прогресса")
        state["episodesDone"] = new_total
    item.tracking, item.updated = state, max(item.updated + 1, now_ms())
    if item.status == "plan" and (episode_delta > 0 or season_delta > 0):
        set_status(db, item, "watching")
    record(db, item, "progress", episodes=episode_delta, seasons=season_delta)


def list_items(db, filters):
    query = select(Item)
    if filters.type:
        query = query.where(Item.type == filters.type)
    if filters.status:
        query = query.where(Item.status == filters.status)
    if filters.active:
        query = query.where(Item.status.in_(("watching", "rewatching")))
    if filters.year:
        query = query.where(Item.year == filters.year)
    if filters.favorite is not None:
        query = query.where(Item.favorite == filters.favorite)
    if filters.rating_min:
        query = query.where(Item.rating >= filters.rating_min)
    if filters.rating_max:
        query = query.where(Item.rating <= filters.rating_max)
    if filters.genre:
        query = query.where(Item.genre_search.contains(genre_key([filters.genre]), autoescape=True))
    if filters.q:
        for term in normalize(filters.q).split():
            query = query.where(Item.search_text.contains(term, autoescape=True))
    episodes_done = Item.tracking["episodesDone"].as_integer()
    episodes_total = Item.tracking["episodesTotal"].as_integer()
    done = case(
        (
            (func.coalesce(episodes_total, 0) > 0) | (func.coalesce(episodes_done, 0) > 0),
            episodes_done,
        ),
        else_=Item.seasons_done,
    )
    total = case(
        (
            (func.coalesce(episodes_total, 0) > 0) | (func.coalesce(episodes_done, 0) > 0),
            episodes_total,
        ),
        else_=Item.seasons_total,
    )
    if filters.unfinished:
        query = query.where(done > 0, (total == 0) | (done < total), Item.status != "watched")
    progress = cast(done, Float) / func.nullif(total, 0)
    order = {
        "title": Item.title.asc(),
        "added": Item.added.desc(),
        "updated": Item.updated.desc(),
        "year": Item.year.desc().nulls_last(),
        "rating": Item.rating.desc().nulls_last(),
        "progress": func.coalesce(progress, literal(0)).desc(),
    }[filters.sort]
    count = db.scalar(select(func.count()).select_from(query.subquery()))
    page = (
        query.order_by(order, Item.id)
        .limit(filters.limit)
        .offset((filters.page - 1) * filters.limit)
    )
    return {
        "items": [archive_item(i) for i in db.scalars(page)],
        "total": count,
        "page": filters.page,
        "limit": filters.limit,
    }
