import asyncio
import re
import time
from collections import OrderedDict
from html.parser import HTMLParser

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas import ItemInput

ANILIST = "https://graphql.anilist.co"
TMDB = "https://api.themoviedb.org/3"
ANIME_FIELDS = """
id title { romaji english native } synonyms startDate { year month day }
coverImage { large } bannerImage description(asHtml: false) genres episodes duration status averageScore
nextAiringEpisode { episode airingAt }
relations { edges { relationType node { id type title { romaji english native } } } }
"""
ANIME_SEARCH = """query ($q: String!) { Page(page: 1, perPage: 12) {
Media(search: $q, type: ANIME, isAdult: false) {
id title { romaji english native } startDate { year } coverImage { large }
} } }"""
ANIME_DETAIL = "query ($id: Int!) { Media(id: $id, type: ANIME) {" + ANIME_FIELDS + "} }"


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, _):
        if tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")


def plain(value):
    parser = PlainText()
    parser.feed(value or "")
    parser.close()
    return "".join(parser.parts).strip()[:30000]


def anime_title(titles):
    return titles.get("english") or titles.get("romaji") or titles.get("native")


def anime_record(raw):
    titles = raw["title"]
    release = raw.get("startDate", {})
    year = release.get("year")
    release_date = (
        f"{year:04}-{release['month']:02}-{release['day']:02}"
        if all(release.get(key) for key in ("year", "month", "day"))
        else None
    )
    next_episode = raw.get("nextAiringEpisode") or {}
    relations = []
    for edge in (raw.get("relations") or {}).get("edges", [])[:50]:
        other = edge["node"]
        if other["type"] == "ANIME" and anime_title(other["title"]):
            relations.append(
                {
                    "id": other["id"],
                    "title": anime_title(other["title"]),
                    "relation": edge.get("relationType") or "",
                }
            )
    score = raw.get("averageScore")
    return ItemInput.model_validate(
        {
            "type": "anime",
            "title": anime_title(titles),
            "year": year,
            "status": "plan",
            "genres": (raw.get("genres") or [])[:40],
            "episodesTotal": raw.get("episodes") or 0,
            "metadata": {
                "provider": "anilist",
                "fetchedAt": time.time_ns() // 1_000_000,
                "externalId": raw["id"],
                "originalTitle": titles.get("native"),
                "romajiTitle": titles.get("romaji"),
                "alternateTitles": [
                    s for s in raw.get("synonyms") or [] if s.strip() and len(s) <= 500
                ][:50],
                "poster": (raw.get("coverImage") or {}).get("large"),
                "backdrop": raw.get("bannerImage"),
                "description": plain(raw.get("description")),
                "releaseDate": release_date,
                "releaseStatus": raw.get("status"),
                "runtime": raw.get("duration") or None,
                "communityRating": score / 10 if score is not None else None,
                "nextEpisode": next_episode.get("episode"),
                "nextAiring": next_episode["airingAt"] * 1000
                if next_episode.get("airingAt")
                else None,
                "related": relations,
            },
        }
    )


def tmdb_image(path, size, config):
    if not isinstance(path, str) or not re.fullmatch(r"/[a-zA-Z0-9_-]+\.(jpg|png|webp)", path):
        return None
    images = config.get("images", {})
    key = "poster_sizes" if size == "w342" else "backdrop_sizes"
    base = images.get("secure_base_url", "")
    if base != "https://image.tmdb.org/t/p/":
        base = "https://image.tmdb.org/t/p/"
    if size not in images.get(key, []):
        size = images.get(key, ["original"])[-1] if images.get(key) else size
    if not re.fullmatch(r"w[0-9]+|original", size):
        return None
    return base + size + path


def film_record(raw, config):
    release = raw.get("release_date") or None
    alternatives = (raw.get("alternative_titles") or {}).get("titles", [])
    votes = raw.get("vote_count") or 0
    return ItemInput.model_validate(
        {
            "type": "film",
            "title": raw.get("title") or raw.get("original_title"),
            "year": int(release[:4]) if release else None,
            "status": "plan",
            "genres": [genre["name"] for genre in raw.get("genres") or []][:40],
            "metadata": {
                "provider": "tmdb",
                "fetchedAt": time.time_ns() // 1_000_000,
                "externalId": raw["id"],
                "originalTitle": raw.get("original_title"),
                "alternateTitles": list(
                    dict.fromkeys(
                        t["title"]
                        for t in alternatives
                        if t.get("title") and len(t["title"]) <= 500
                    )
                )[:50],
                "poster": tmdb_image(raw.get("poster_path"), "w342", config),
                "backdrop": tmdb_image(raw.get("backdrop_path"), "w780", config),
                "description": plain(raw.get("overview")),
                "releaseDate": release,
                "releaseStatus": raw.get("status"),
                "runtime": raw.get("runtime") or None,
                "communityRating": raw.get("vote_average") if votes else None,
            },
        }
    )


class Catalog:
    def __init__(self, client, settings):
        self.client = client
        self.settings = settings
        self.cache = OrderedDict()
        self.parallel = asyncio.Semaphore(3)
        self.cooldowns = {}

    def enabled(self):
        return {"anilist": self.settings.anilist, "tmdb": bool(self.settings.tmdb_token)}

    async def fetch(self, provider, method, url, ttl=900, **options):
        key = (provider, url, repr(sorted(options.items())))
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            self.cache.move_to_end(key)
            return cached[1]
        async with self.parallel:
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                self.cache.move_to_end(key)
                return cached[1]
            if self.cooldowns.get(provider, 0) > time.monotonic():
                delay = max(1, int(self.cooldowns[provider] - time.monotonic()))
                raise HTTPException(
                    429, "Каталог ограничил частоту запросов", headers={"Retry-After": str(delay)}
                )
            headers = (
                {"Authorization": f"Bearer {self.settings.tmdb_token}"}
                if provider == "tmdb"
                else {}
            )
            for attempt in range(2):
                try:
                    response = await self.client.request(method, url, headers=headers, **options)
                    if response.status_code == 404:
                        raise HTTPException(404, "Произведение не найдено в каталоге")
                    if response.status_code == 429:
                        value = response.headers.get("Retry-After", "60")
                        delay = (
                            max(1, min(3600, int(value)))
                            if value.isascii() and value.isdecimal() and len(value) < 8
                            else 60
                        )
                        self.cooldowns[provider] = time.monotonic() + delay
                        raise HTTPException(
                            429,
                            "Каталог ограничил частоту запросов",
                            headers={"Retry-After": str(delay)},
                        )
                    if 500 <= response.status_code < 600 and attempt == 0:
                        await asyncio.sleep(0.15)
                        continue
                    if not response.is_success:
                        break
                    data = response.json()
                    if not isinstance(data, dict) or data.get("errors"):
                        break
                    self.cache[key] = (time.monotonic() + ttl, data)
                    self.cache.move_to_end(key)
                    while len(self.cache) > 128:
                        self.cache.popitem(last=False)
                    return data
                except httpx.TransportError:
                    if attempt == 0:
                        await asyncio.sleep(0.15)
                        continue
                except ValueError:
                    break
        raise HTTPException(502, "Каталог временно недоступен")

    async def lookup(self, provider, query=None, catalog_id=None):
        if not self.enabled()[provider]:
            raise HTTPException(503, "Интеграция с каталогом отключена")
        try:
            if provider == "anilist":
                result = await self.fetch(
                    provider,
                    "POST",
                    ANILIST,
                    json={
                        "query": ANIME_SEARCH if query is not None else ANIME_DETAIL,
                        "variables": {"q": query} if query is not None else {"id": catalog_id},
                    },
                )
                if query is not None:
                    rows = result["data"]["Page"]["Media"]
                    return self.parse_search(rows, anime_record)
                row = result["data"]["Media"]
                if not row:
                    raise HTTPException(404, "Произведение не найдено в каталоге")
                return anime_record(row)
            config = await self.fetch(provider, "GET", TMDB + "/configuration", ttl=86400)
            if query is not None:
                result = await self.fetch(
                    provider,
                    "GET",
                    TMDB + "/search/movie",
                    params={"query": query, "language": "ru-RU", "include_adult": "false"},
                )
                return self.parse_search(result["results"], lambda row: film_record(row, config))
            result = await self.fetch(
                provider,
                "GET",
                f"{TMDB}/movie/{catalog_id}",
                params={"language": "ru-RU", "append_to_response": "alternative_titles"},
            )
            return film_record(result, config)
        except (KeyError, TypeError, ValueError, AttributeError, ValidationError) as exc:
            raise HTTPException(502, "Каталог вернул некорректные данные") from exc

    @staticmethod
    def parse_search(rows, parse):
        result = []
        for row in rows[:12]:
            try:
                result.append(parse(row))
            except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
                continue
        return result
