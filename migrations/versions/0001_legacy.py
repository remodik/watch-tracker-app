"""Adopt the original items table or create its baseline on a new database."""

import sqlalchemy as sa
from alembic import op

revision = "0001_legacy"
down_revision = None

LEGACY_COLUMNS = {
    "id",
    "added",
    "type",
    "title",
    "year",
    "status",
    "genres",
    "seasonsDone",
    "seasonsTotal",
    "note",
}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("items"):
        columns = {c["name"] for c in inspector.get_columns("items")}
        primary_key = inspector.get_pk_constraint("items")["constrained_columns"]
        if columns != LEGACY_COLUMNS or primary_key != ["id"]:
            raise RuntimeError("Unexpected items schema. Restore or inspect a database copy first.")
        return
    op.create_table(
        "items",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("added", sa.BigInteger, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("year", sa.Integer),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("genres", sa.Text, nullable=False),
        sa.Column("seasonsDone", sa.Integer, nullable=False),
        sa.Column("seasonsTotal", sa.Integer, nullable=False),
        sa.Column("note", sa.Text, nullable=False),
    )


def downgrade():
    raise RuntimeError(
        "This revision adopts existing data. Restore a database backup to roll back."
    )
