"""Add searchable identities, progress history, backups and revocable sessions."""

import sqlalchemy as sa
from alembic import op

from app.identity import decode_genres, genre_key, match_key, search_key

revision = "0002_library"
down_revision = "0001_legacy"


def upgrade():
    for column in (
        sa.Column("updated", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("match_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("identity_key", sa.String(64)),
        sa.Column("search_text", sa.Text, nullable=False, server_default=""),
        sa.Column("genre_search", sa.Text, nullable=False, server_default=""),
        sa.Column("favorite", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("rating", sa.Integer),
        sa.Column("tracking", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON, nullable=False, server_default="{}"),
    ):
        op.add_column("items", column)
    table = sa.table(
        "items",
        *(
            sa.column(name)
            for name in (
                "id",
                "title",
                "type",
                "year",
                "genres",
                "note",
                "added",
                "updated",
                "match_key",
                "identity_key",
                "search_text",
                "genre_search",
            )
        ),
    )
    db = op.get_bind()
    claimed = set()
    last = None
    while True:
        query = sa.select(table).order_by(table.c.id).limit(500)
        if last is not None:
            query = query.where(table.c.id > last)
        entries = db.execute(query).mappings().all()
        if not entries:
            break
        for row in entries:
            key = match_key(row["title"], row["type"], row["year"])
            genres = decode_genres(row["genres"])
            db.execute(
                table.update()
                .where(table.c.id == row["id"])
                .values(
                    updated=row["added"],
                    match_key=key,
                    identity_key=None if key in claimed else key,
                    search_text=search_key(row["title"], genres, row["note"], row["year"], {}),
                    genre_search=genre_key(genres),
                )
            )
            claimed.add(key)
        last = entries[-1]["id"]
    op.create_index("uq_items_identity", "items", ["identity_key"], unique=True)
    for fields in (
        ("added",),
        ("updated",),
        ("type", "status"),
        ("year",),
        ("favorite",),
        ("rating",),
        ("match_key",),
    ):
        op.create_index("ix_items_" + "_".join(fields), "items", list(fields))
    op.create_table(
        "watch_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "item_id", sa.String, sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("at", sa.BigInteger, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
    )
    op.create_index("ix_watch_events_at", "watch_events", ["at"])
    op.create_index("ix_watch_events_item_id", "watch_events", ["item_id"])
    op.create_table(
        "backups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created", sa.BigInteger, nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("archive", sa.JSON, nullable=False),
    )
    op.create_index("ix_backups_created", "backups", ["created"])
    for name in ("library_lock", "login_lock"):
        table = op.create_table(name, sa.Column("id", sa.Integer, primary_key=True))
        op.bulk_insert(table, [{"id": 1}])
    op.create_table(
        "auth_sessions",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("expires", sa.BigInteger, nullable=False),
    )
    op.create_index("ix_auth_sessions_expires", "auth_sessions", ["expires"])
    op.create_table(
        "login_failures",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client", sa.String(64), nullable=False),
        sa.Column("at", sa.BigInteger, nullable=False),
    )
    op.create_index("ix_login_failures_client", "login_failures", ["client"])
    op.create_index("ix_login_failures_at", "login_failures", ["at"])


def downgrade():
    raise RuntimeError("Restore a pre-upgrade database backup to roll back without data loss.")
