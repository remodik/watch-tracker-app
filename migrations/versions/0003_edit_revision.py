"""Separate the edit token and collection generation from archive metadata."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0003_edit_revision"
down_revision = "0002_library"


def upgrade():
    # Existing records can share an initial token because checks also bind the item ID.
    initial = str(uuid4())
    op.add_column(
        "items", sa.Column("revision", sa.String(36), nullable=False, server_default=initial)
    )
    op.add_column(
        "library_lock",
        sa.Column("generation", sa.String(36), nullable=False, server_default=initial),
    )


def downgrade():
    raise RuntimeError("Restore the pre-upgrade backup to downgrade safely.")
