from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    added: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    genres_json: Mapped[str] = mapped_column("genres", Text)
    seasons_done: Mapped[int] = mapped_column("seasonsDone", Integer)
    seasons_total: Mapped[int] = mapped_column("seasonsTotal", Integer)
    note: Mapped[str] = mapped_column(Text)
    updated: Mapped[int] = mapped_column(BigInteger, index=True)
    revision: Mapped[str] = mapped_column(String(36))
    match_key: Mapped[str] = mapped_column(String(64), index=True)
    identity_key: Mapped[str | None] = mapped_column(String(64))
    search_text: Mapped[str] = mapped_column(Text)
    genre_search: Mapped[str] = mapped_column(Text)
    favorite: Mapped[bool] = mapped_column(Boolean, index=True)
    rating: Mapped[int | None] = mapped_column(Integer, index=True)
    tracking: Mapped[dict] = mapped_column(JSON)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (
        Index("ix_items_added", "added"),
        Index("ix_items_type_status", "type", "status"),
        Index("ix_items_year", "year"),
        Index("uq_items_identity", "identity_key", unique=True),
    )


class WatchEvent(Base):
    __tablename__ = "watch_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    at: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON)


class Backup(Base):
    __tablename__ = "backups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created: Mapped[int] = mapped_column(BigInteger, index=True)
    reason: Mapped[str] = mapped_column(String(20))
    archive: Mapped[dict] = mapped_column(JSON)
    size_bytes: Mapped[int] = mapped_column(BigInteger)


class LibraryLock(Base):
    __tablename__ = "library_lock"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generation: Mapped[str] = mapped_column(String(36))


class LoginLock(Base):
    __tablename__ = "login_lock"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires: Mapped[int] = mapped_column(BigInteger, index=True)


class LoginFailure(Base):
    __tablename__ = "login_failures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[int] = mapped_column(BigInteger, index=True)
