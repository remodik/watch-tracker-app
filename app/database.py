from uuid import uuid4

from fastapi import HTTPException
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


def make_sessions(engine, settings=None):
    return sessionmaker(engine, expire_on_commit=False, info={"settings": settings})


def lock_library(db):
    # A write on SQLite and a row lock on PostgreSQL serialize collection changes.
    generation = db.execute(
        update(LibraryLock)
        .where(LibraryLock.id == 1)
        .values(id=1)
        .returning(LibraryLock.generation)
    ).scalar_one_or_none()
    if generation is None:
        raise HTTPException(503, "Блокировка коллекции недоступна")
    db.execute(update(LibraryLock).where(LibraryLock.id == 1).values(generation=str(uuid4())))
    return generation


def begin_library_snapshot(db):
    if db.get_bind().dialect.name == "postgresql":
        connection = db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    else:
        db.connection().exec_driver_sql("BEGIN")
