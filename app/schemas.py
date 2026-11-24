from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.viewing_time import today

Kind = Literal["anime", "film"]
Status = Literal["plan", "watching", "watched", "paused", "dropped", "rewatching"]
Provider = Literal["anilist", "tmdb"]
ImportMode = Literal["merge", "update", "replace"]
Sort = Literal["title", "added", "updated", "year", "rating", "progress"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def clean_genre(value):
    if isinstance(value, str) and any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise ValueError("Недопустимый символ в жанре")
    return value


Genre = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
    BeforeValidator(clean_genre),
]
EpisodeCount = Annotated[int, Field(ge=0, le=100_000)]
SeasonCount = Annotated[int, Field(ge=0, le=999)]
PositiveSeason = Annotated[int, Field(ge=1, le=999)]
Timestamp = Annotated[int, Field(ge=0, le=253402300799999)]
ExternalId = Annotated[int, Field(ge=1, le=2_147_483_647)]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=500, pattern=r"^[^\x00]+$")]
ImageUrl = Annotated[str, StringConstraints(max_length=2048)]
Rating = Annotated[int, Field(ge=1, le=10)]
Year = Annotated[int, Field(ge=1870, le=2200)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    @field_validator("*")
    @classmethod
    def reject_nul(cls, value):
        if isinstance(value, str) and any(c == "\0" or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("Недопустимый символ")
        if isinstance(value, list) and any(
            isinstance(v, str) and any(c == "\0" or 0xD800 <= ord(c) <= 0xDFFF for c in v)
            for v in value
        ):
            raise ValueError("Недопустимый символ")
        return value


class Login(Input):
    token: Annotated[str, Field(min_length=1, max_length=1024)]


class Season(Input):
    number: PositiveSeason
    episodesTotal: EpisodeCount = 0
    episodesDone: EpisodeCount = 0
    watchedEpisodes: Annotated[
        list[Annotated[int, Field(ge=1, le=100_000)]], Field(max_length=5000)
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self):
        if self.episodesTotal and self.episodesDone > self.episodesTotal:
            raise ValueError("Просмотрено больше эпизодов, чем существует")
        if len(set(self.watchedEpisodes)) != len(self.watchedEpisodes):
            raise ValueError("Эпизоды повторяются")
        if self.watchedEpisodes and (
            self.episodesDone != len(self.watchedEpisodes)
            or self.episodesTotal
            and max(self.watchedEpisodes) > self.episodesTotal
        ):
            raise ValueError("Проверьте номера и количество просмотренных эпизодов")
        return self


class Related(Input):
    id: ExternalId
    title: Title
    relation: Annotated[str, StringConstraints(max_length=40)]


def iso_date(value):
    if value is not None:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Дата должна иметь формат ГГГГ-ММ-ДД")
    return value


def viewing_date(value):
    value = iso_date(value)
    if value and value > today():
        raise ValueError("Дата просмотра не может быть в будущем")
    return value


class Metadata(Input):
    provider: Provider | None = None
    externalId: ExternalId | None = None
    originalTitle: Title | None = None
    romajiTitle: Title | None = None
    alternateTitles: Annotated[list[Title], Field(max_length=50)] = Field(default_factory=list)
    poster: ImageUrl | None = None
    backdrop: ImageUrl | None = None
    description: Annotated[str, StringConstraints(max_length=30000)] = ""
    releaseDate: Annotated[str, StringConstraints(max_length=10)] | None = None
    releaseStatus: Annotated[str, StringConstraints(max_length=80)] | None = None
    runtime: Annotated[int, Field(ge=1, le=3000)] | None = None
    communityRating: Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)] | None = None
    nextEpisode: Annotated[int, Field(ge=1, le=100_000)] | None = None
    nextAiring: Timestamp | None = None
    fetchedAt: Timestamp | None = None
    related: Annotated[list[Related], Field(max_length=50)] = Field(default_factory=list)

    _check_date = field_validator("releaseDate")(iso_date)

    @field_validator("poster", "backdrop")
    @classmethod
    def image_url(cls, value):
        if value is not None:
            if any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
                raise ValueError("Некорректный адрес изображения")
            url = urlsplit(value)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("Укажите абсолютный HTTPS-адрес изображения")
            _ = url.port
        return value

    @model_validator(mode="after")
    def consistent(self):
        if bool(self.externalId) != bool(self.provider):
            raise ValueError("Каталог и его идентификатор указываются вместе")
        if (
            bool(self.nextEpisode) != bool(self.nextAiring)
            or self.nextAiring
            and self.provider != "anilist"
        ):
            raise ValueError("Релиз должен содержать номер эпизода, дату и источник")
        return self


class ItemInput(Input):
    type: Kind = "anime"
    title: Title
    year: Year | None = None
    status: Status = "watched"
    genres: Annotated[list[Genre], Field(max_length=40)] = Field(default_factory=list)
    seasonsDone: SeasonCount = 0
    seasonsTotal: SeasonCount = 0
    note: Annotated[str, StringConstraints(max_length=30000)] = ""
    favorite: bool = False
    rating: Rating | None = None
    episodesDone: EpisodeCount = 0
    episodesTotal: EpisodeCount = 0
    episodesTotalFromSeasons: bool = False
    seasons: Annotated[list[Season], Field(max_length=999)] = Field(default_factory=list)
    started: Annotated[str, StringConstraints(max_length=10)] | None = None
    completed: Annotated[str, StringConstraints(max_length=10)] | None = None
    carriedEpisodes: Annotated[int, Field(ge=0, le=1_000_000_000)] = 0
    rewatchInProgress: bool = False
    hasCompleted: bool = False
    rewatches: Annotated[int, Field(ge=0, le=9999)] = 0
    metadata: Metadata = Field(default_factory=Metadata)

    _check_dates = field_validator("started", "completed")(viewing_date)

    @model_validator(mode="after")
    def consistent(self):
        if self.seasonsTotal and self.seasonsDone > self.seasonsTotal:
            raise ValueError("Просмотрено больше сезонов, чем существует")
        if self.episodesTotal and self.episodesDone > self.episodesTotal:
            raise ValueError("Просмотрено больше эпизодов, чем существует")
        if self.type == "film" and any(
            (
                self.seasons,
                self.seasonsTotal,
                self.seasonsDone,
                self.episodesTotal,
                self.episodesDone,
                self.carriedEpisodes,
            )
        ):
            raise ValueError("Сезоны и эпизоды доступны для аниме")
        if self.started and self.completed and self.started > self.completed:
            raise ValueError("Дата начала позже даты завершения")
        if self.metadata.provider and (self.type == "anime") != (
            self.metadata.provider == "anilist"
        ):
            raise ValueError("Каталог не соответствует типу произведения")
        numbers = {season.number for season in self.seasons}
        if (
            len(numbers) != len(self.seasons)
            or self.seasonsTotal
            and numbers
            and max(numbers) > self.seasonsTotal
        ):
            raise ValueError("Проверьте номера сезонов")
        if sum(s.episodesDone for s in self.seasons) > self.episodesDone:
            raise ValueError("Прогресс сезонов превышает общий прогресс")
        return self


class ArchiveItem(ItemInput):
    _check_dates = field_validator("started", "completed")(iso_date)
    id: Identifier | None = None
    legacyDuplicate: bool = False
    added: Timestamp | None = None
    updated: Timestamp | None = None


class EventData(Input):
    episodes: Annotated[int, Field(ge=-100_000, le=100_000)] = 0
    seasons: Annotated[int, Field(ge=-999, le=999)] = 0
    status: Status | None = None
    runtime: Annotated[int, Field(ge=1, le=3000)] | None = None
    completion: bool | None = None
    film: bool = False
    rewatch: bool = False


class ArchiveEvent(Input):
    id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f-]{36}$")]
    item_id: Identifier
    at: Timestamp
    kind: Literal["progress", "status"]
    data: EventData


class ArchiveRequest(Input):
    mode: ImportMode
    version: Annotated[int, Field(ge=1, le=2)] = 1
    items: list[object]
    events: list[object] = Field(default_factory=list)
    confirm: bool = False


class ImportRequest(ArchiveRequest):
    items: Annotated[list[object], Field(max_length=10000)]
    events: Annotated[list[object], Field(max_length=50000)] = Field(default_factory=list)


class BackupRestore(Input):
    preview: Identifier
    confirm: Literal[True]


class Progress(Input):
    delta: Annotated[int, Field(ge=-1, le=1)] = 1
    unit: Literal["auto", "episode", "season"] = "auto"
    season: PositiveSeason | None = None
    episode: Annotated[int, Field(ge=1, le=100_000)] | None = None
    watched: bool | None = None

    @field_validator("delta")
    @classmethod
    def nonzero_delta(cls, value):
        if value == 0:
            raise ValueError("Выберите увеличение или уменьшение прогресса")
        return value

    @model_validator(mode="after")
    def consistent(self):
        if (
            (self.episode is None) != (self.watched is None)
            or self.episode
            and (self.season is None or self.unit != "episode")
        ):
            raise ValueError("Для отдельного эпизода укажите сезон и отметку просмотра")
        return self


class StatusChange(Input):
    status: Status


class FavoriteChange(Input):
    favorite: bool


class ItemFilters(Input):
    model_config = ConfigDict(extra="forbid", strict=False)
    type: Kind | None = None
    status: Status | None = None
    year: Year | None = None
    genre: Genre | None = None
    q: Annotated[str, StringConstraints(max_length=160)] | None = None
    rating_min: Rating | None = None
    rating_max: Rating | None = None
    favorite: bool | None = None
    active: bool = False
    unfinished: bool = False
    sort: Sort = "added"
    page: Annotated[int, Field(ge=1, le=10000)] = 1
    limit: Annotated[int, Field(ge=1, le=100)] = 36

    @model_validator(mode="after")
    def consistent(self):
        if self.rating_min and self.rating_max and self.rating_min > self.rating_max:
            raise ValueError("Проверьте диапазон оценок")
        return self
