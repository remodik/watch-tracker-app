import hashlib
import json
import unicodedata


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def fingerprint(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def match_key(title, kind, year):
    return fingerprint(normalize(title), kind, year)


def search_key(title, genres, note, year, metadata):
    return normalize(
        " ".join(
            [
                title,
                *genres,
                note,
                str(year or ""),
                metadata.get("originalTitle") or "",
                metadata.get("romajiTitle") or "",
                *(metadata.get("alternateTitles") or []),
            ]
        )
    )


def genre_key(genres):
    return "\x1f" + "\x1f".join(normalize(g) for g in genres) + "\x1f"


def decode_genres(value):
    try:
        genres = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [genre for genre in genres if isinstance(genre, str)] if isinstance(genres, list) else []
