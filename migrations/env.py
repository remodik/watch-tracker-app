from alembic import context
from dotenv import load_dotenv
from sqlalchemy import text

from app.config import database_url
from app.database import make_engine
from app.models import Base

load_dotenv()
engine = make_engine(database_url(direct=True))
if context.is_offline_mode():
    raise RuntimeError("Online mode is required to inspect the legacy schema")

with engine.connect() as connection, connection.begin():
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    elif connection.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(798416132)"))
    context.configure(connection=connection, target_metadata=Base.metadata, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
