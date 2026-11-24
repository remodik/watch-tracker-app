from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import sessionmaker

from app.models import LibraryLock


def make_engine(url):
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")

    return engine


def make_sessions(engine):
    return sessionmaker(engine, expire_on_commit=False)


def lock_library(db):
    # A write on SQLite and a row lock on PostgreSQL serialize collection changes.
    db.execute(update(LibraryLock).where(LibraryLock.id == 1).values(id=1))
