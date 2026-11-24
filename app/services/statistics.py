from collections import Counter, defaultdict
from datetime import UTC, datetime
from heapq import nsmallest

from sqlalchemy import select

from app.identity import decode_genres, normalize
from app.models import Item, WatchEvent


def date_at(timestamp, zone):
    try:
        return datetime.fromtimestamp(timestamp / 1000, tz=zone)
    except (OverflowError, ValueError, OSError):
        return None


def summary_items(db):
    fields = Item.tracking
    return db.execute(
        select(
            Item.type,
            Item.status,
            Item.year,
            Item.rating,
            Item.genres_json,
            Item.added,
            fields["episodesDone"].as_integer().label("episodes"),
            fields["carriedEpisodes"].as_integer().label("carried"),
            fields["rewatches"].as_integer().label("rewatches"),
            fields["rewatchInProgress"].as_boolean().label("rewatching"),
            fields["completed"].as_string().label("completed"),
            fields["hasCompleted"].as_boolean().label("completed_once"),
            Item.metadata_json["runtime"].as_integer().label("runtime"),
        )
    ).all()


def distributions(items):
    counts = {name: Counter() for name in ("types", "statuses", "years", "ratings", "genres")}
    labels = {}
    episodes = rewatches = minutes = known = tracked = 0
    for item in items:
        counts["types"][item.type] += 1
        counts["statuses"][item.status] += 1
        if item.year is not None:
            counts["years"][item.year] += 1
        if item.rating is not None:
            counts["ratings"][item.rating] += 1
        genres = {normalize(g): g for g in decode_genres(item.genres_json)}
        labels.update({key: value for key, value in genres.items() if key not in labels})
        counts["genres"].update(genres.keys())
        repeats = item.rewatches or 0
        episode_count = (item.episodes or 0) + (item.carried or 0)
        episodes += episode_count
        rewatches += repeats
        units = (
            episode_count
            if item.type == "anime"
            else (
                int(
                    bool(
                        item.status == "watched"
                        or item.completed
                        or item.completed_once
                        or item.rewatching
                        or repeats
                    )
                )
                + repeats
            )
        )
        tracked += units
        runtime = item.runtime
        if units and runtime:
            known += units
            minutes += runtime * units
    counts["genres"] = Counter({labels[key]: value for key, value in counts["genres"].items()})
    return {
        **{key: dict(value) for key, value in counts.items()},
        "total": len(items),
        "episodes": episodes,
        "rewatches": rewatches,
        "estimatedMinutes": minutes if known else None,
        "knownDurationUnits": known,
        "trackedUnits": tracked,
    }


def report(db, year, zone):
    items = summary_items(db)
    stats = distributions(items)
    months = {name: defaultdict(int) for name in ("additions", "completed", "episodes")}
    activity = defaultdict(int)
    annual = {
        "year": year,
        "added": 0,
        "completed": 0,
        "episodes": 0,
        "rewatches": 0,
        "estimatedMinutes": None,
    }
    for item in items:
        date = date_at(item.added, zone)
        if date is not None:
            months["additions"][date.strftime("%Y-%m")] += 1
            if date.year == year:
                annual["added"] += 1
    estimated = 0
    known = False
    for event in db.scalars(
        select(WatchEvent).order_by(WatchEvent.at).execution_options(yield_per=500)
    ):
        date = date_at(event.at, zone)
        if date is None:
            continue
        data = event.data
        month = date.strftime("%Y-%m")
        completed = int(
            event.kind == "status"
            and data.get("status") == "watched"
            and data.get("completion") is not False
        )
        episodes = data.get("episodes", 0)
        if completed:
            months["completed"][month] += completed
        if episodes:
            months["episodes"][month] += episodes
        if date.year == year:
            if completed or episodes > 0 or data.get("seasons", 0) > 0:
                activity[date.date().isoformat()] += 1
            annual["completed"] += completed
            annual["episodes"] += episodes
            annual["rewatches"] += int(bool(data.get("rewatch")))
            if (episodes or data.get("film")) and data.get("runtime"):
                known = True
                estimated += data["runtime"] * (episodes + int(bool(data.get("film"))))
    if known:
        annual["estimatedMinutes"] = max(0, estimated)
    annual["episodes"] = max(0, annual["episodes"])
    months["episodes"] = {month: max(0, count) for month, count in months["episodes"].items()}
    return {**stats, "months": months, "activity": dict(activity), "annual": annual}


def upcoming(db, limit=100):
    now = int(datetime.now(UTC).timestamp() * 1000)
    rows = db.execute(
        select(Item.id, Item.title, Item.metadata_json)
        .where(
            Item.type == "anime",
            Item.status.in_(["plan", "watching", "rewatching", "paused"]),
            Item.metadata_json["provider"].as_string() == "anilist",
        )
        .execution_options(yield_per=200)
    )

    def validated():
        for item_id, title, metadata in rows:
            episode, airing = metadata.get("nextEpisode"), metadata.get("nextAiring")
            if (
                type(episode) is int
                and 1 <= episode <= 100_000
                and type(airing) is int
                and now <= airing <= 253402300799999
            ):
                yield {
                    "id": item_id,
                    "title": title,
                    "episode": episode,
                    "at": airing,
                    "source": "anilist",
                    "status": "scheduled",
                }

    return nsmallest(limit, validated(), key=lambda item: (item["at"], item["id"]))
