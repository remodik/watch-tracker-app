"""Store the logical JSON size of each backup."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0004_backup_size"
down_revision = "0003_edit_revision"


def upgrade():
    op.add_column(
        "backups", sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0")
    )
    table = sa.table(
        "backups", sa.column("id"), sa.column("archive", sa.JSON), sa.column("size_bytes")
    )
    connection = op.get_bind()
    last = ""
    while batch := connection.execute(
        sa.select(table.c.id, table.c.archive)
        .where(table.c.id > last)
        .order_by(table.c.id)
        .limit(20)
    ).all():
        for row in batch:
            size = len(json.dumps(row.archive, ensure_ascii=False, separators=(",", ":")).encode())
            connection.execute(table.update().where(table.c.id == row.id).values(size_bytes=size))
        last = batch[-1].id


def downgrade():
    op.drop_column("backups", "size_bytes")
