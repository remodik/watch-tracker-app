import asyncio
import logging
import re
import time
from collections import OrderedDict
from datetime import date
from html.parser import HTMLParser

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from app.identity import normalize
from app.schemas import ItemInput, Related

logger = logging.getLogger(__name__)

ANILIST = "https://graphql.anilist.co"
TMDB = "https://api.themoviedb.org/3"
ANIME_FIELDS = """
id title { romaji english native } synonyms startDate { year month day }
coverImage { large } bannerImage description(asHtml: false) genres episodes duration status averageScore
nextAiringEpisode { episode airingAt }
relations { edges { relationType node { id type title { romaji english native } } } }
"""
ANIME_SEARCH = """query ($q: String!) { Page(page: 1, perPage: 12) {
media(search: $q, type: ANIME, isAdult: false) {
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


def optional_object(value):
    return value if isinstance(value, dict) else {}


def optional_list(value):
    return value if isinstance(value, list) else []


def title_string(value):
    if isinstance(value, str):
        value = value.strip()
        if 0 < len(value) <= 500 and "\0" not in value:
            return value
    return None


def alternatives(values):
    titles = {}
    for raw in values:
        title = title_string(raw)
        if title:
            titles.setdefault(normalize(title), title)
            if len(titles) == 50:
                break
    return list(titles.values())


def anime_title(titles):
    return next(
        (
            title
            for key in ("english", "romaji", "native")
            if (title := title_string(titles.get(key)))
        ),
        None,
    )


def bounded_int(value, low, high):
    return value if type(value) is int and low <= value <= high else None


def anime_record(raw):
    titles = optional_object(raw.get("title"))
    release = optional_object(raw.get("startDate"))
    year = bounded_int(release.get("year"), 1870, 2200)
    try:
        release_date = date(year, release.get("month"), release.get("day")).isoformat()
    except (TypeError, ValueError):
        release_date = None
    next_episode = optional_object(raw.get("nextAiringEpisode"))
    episode = bounded_int(next_episode.get("episode"), 1, 100_000)
    airing = bounded_int(next_episode.get("airingAt"), 1, 253402300799)
    relations = []
    for edge in optional_list(optional_object(raw.get("relations")).get("edges"))[:50]:
        edge = optional_object(edge)
        other = optional_object(edge.get("node"))
        if other.get("type") == "ANIME":
            try:
                relation = Related(
                    id=other.get("id"),
                    title=anime_title(optional_object(other.get("title"))),
                    relation=edge.get("relationType") or "",
                )
            except ValueError:
                continue
            relations.append(relation.model_dump())
    score = bounded_int(raw.get("averageScore"), 0, 100)
    return ItemInput.model_validate(
        {
            "type": "anime",
            "title": anime_title(titles),
            "year": year,
            "status": "plan",
            "genres": (raw.get("genres") or [])[:40],
            "episodesTotal": bounded_int(raw.get("episodes"), 1, 100_000) or 0,
            "metadata": {
                "provider": "anilist",
                "fetchedAt": time.time_ns() // 1_000_000,
                "externalId": raw["id"],
                "originalTitle": title_string(titles.get("native")),
                "romajiTitle": title_string(titles.get("romaji")),
                "alternateTitles": alternatives(optional_list(raw.get("synonyms"))),
                "poster": optional_object(raw.get("coverImage")).get("large"),
                "backdrop": raw.get("bannerImage"),
                "description": plain(raw.get("description")),
                "releaseDate": release_date,
                "releaseStatus": raw.get("status"),
                "runtime": bounded_int(raw.get("duration"), 1, 3000),
                "communityRating": score / 10 if score is not None else None,
                "nextEpisode": episode if airing else None,
                "nextAiring": airing * 1000 if airing and episode else None,
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
    alternate_entries = optional_list(optional_object(raw.get("alternative_titles")).get("titles"))
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
                "alternateTitles": alternatives(
                    optional_object(entry).get("title") for entry in alternate_entries
                ),
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


def anilist_error_format(response):
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type in {"text/html", "application/xhtml+xml"}:
        return "HTML"
    if media_type not in {"application/json", "application/graphql-response+json"}:
        return "other format"
    try:
        data = response.json()
    except ValueError:
        return "invalid JSON"
    errors = optional_object(data).get("errors")
    if not isinstance(errors, list) or not errors:
        return "JSON"
    categories = sorted({graphql_error_category(error) for error in errors[:10]})
    return "GraphQL errors: " + ", ".join(categories)


def graphql_error_category(raw_error):
    error = optional_object(raw_error)
    code = optional_object(error.get("extensions")).get("code")
    message = error.get("message")
    message = message if isinstance(message, str) else ""
    if code == "GRAPHQL_PARSE_FAILED" or message.startswith("Syntax Error"):
        return "syntax"
    if message.startswith("Variable "):
        return "variables"
    if code == "GRAPHQL_VALIDATION_FAILED" or message.startswith(
        ("Cannot query field ", "Unknown argument ", "Unknown type ")
    ):
        return "validation"
    if code == "INTERNAL_SERVER_ERROR" or isinstance(error.get("path"), list):
        return "execution"
    return "unclassified"


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
                        reason = f"upstream HTTP {response.status_code}"
                        if provider == "anilist":
                            reason += f" [{anilist_error_format(response)}]"
                        break
                    data = response.json()
                    if not isinstance(data, dict) or data.get("errors"):
                        reason = "unexpected payload or provider errors"
                        break
                    self.cache[key] = (time.monotonic() + ttl, data)
                    self.cache.move_to_end(key)
                    while len(self.cache) > 128:
                        self.cache.popitem(last=False)
                    return data
                except httpx.TransportError as exc:
                    if attempt == 0:
                        await asyncio.sleep(0.15)
                        continue
                    reason = type(exc).__name__
                    break
                except ValueError:
                    reason = "invalid JSON"
                    break
        logger.warning("Catalog request failed (%s): %s", provider, reason)
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
                    rows = result["data"]["Page"]["media"]
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
