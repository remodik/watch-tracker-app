import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import load_dotenv


def managed_platform():
    if os.getenv("RENDER") == "true":
        return "Render"
    if os.getenv("RAILWAY_ENVIRONMENT_ID"):
        return "Railway"
    return None


def database_url(*, direct=False):
    url = os.environ.get("DATABASE_URL", "sqlite:///./watchlist.db")
    if direct:
        url = os.getenv("DATABASE_URL_DIRECT") or url
    platform = managed_platform()
    if platform and not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg2://")):
        raise RuntimeError(f"{platform} requires a PostgreSQL DATABASE_URL")
    return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url


@dataclass(frozen=True)
class Settings:
    database_url: str
    environment: str = "production"
    token: str = ""
    disable_auth: bool = False
    origin: str = ""
    anilist: bool = False
    tmdb_token: str = ""
    backup_retention_days: int = 30
    backup_max_automatic_count: int = 20

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            database_url=database_url(),
            environment=os.getenv("APP_ENV", "production"),
            token=os.getenv("APP_TOKEN", ""),
            disable_auth=os.getenv("APP_DISABLE_AUTH") == "1",
            origin=os.getenv("APP_ORIGIN", "").rstrip("/"),
            anilist=os.getenv("ANILIST_ENABLED") == "1",
            tmdb_token=os.getenv("TMDB_READ_TOKEN", ""),
            backup_retention_days=int(os.getenv("BACKUP_RETENTION_DAYS", "30")),
            backup_max_automatic_count=int(os.getenv("BACKUP_MAX_AUTOMATIC_COUNT", "20")),
        )

    @property
    def production(self):
        return self.environment == "production"

    @property
    def cookie_name(self):
        return "__Host-watch_session" if self.production else "watch_session"

    def validate(self):
        if self.backup_retention_days < 1 or self.backup_max_automatic_count < 1:
            raise RuntimeError("Backup retention and count must be positive")
        if self.environment not in {"local", "production"}:
            raise RuntimeError("APP_ENV must be local or production")
        platform = managed_platform()
        if platform and not self.production:
            raise RuntimeError(f"{platform} requires APP_ENV=production")
        if self.disable_auth and self.environment != "local":
            raise RuntimeError("APP_DISABLE_AUTH is restricted to APP_ENV=local")
        if not self.disable_auth and not self.token.strip():
            raise RuntimeError("APP_TOKEN is required")
        if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in self.token):
            raise RuntimeError("APP_TOKEN contains an unsupported character")
        if self.production and len(self.token) < 32:
            raise RuntimeError("APP_TOKEN must contain at least 32 characters in production")
        if len(self.token) > 1024 or len(self.token.encode()) > 4000:
            raise RuntimeError("APP_TOKEN exceeds the supported length")
        if self.origin:
            origin = urlsplit(self.origin)
            if (
                origin.scheme not in ({"https"} if self.production else {"http", "https"})
                or not origin.hostname
                or origin.username
                or origin.password
                or origin.path
                or origin.query
                or origin.fragment
            ):
                raise RuntimeError("APP_ORIGIN must be an absolute origin without a path")
