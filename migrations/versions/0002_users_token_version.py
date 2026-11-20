"""Add users.token_version (SEG-H10).

Replaces the add_token_version_column() patch that ran on every startup.
Idempotent: databases that already went through that patch have the column,
so it is only added when missing.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(col["name"] == column for col in columns)


def upgrade() -> None:
    if _has_column("users", "token_version"):
        return
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "token_version", sa.Integer(), nullable=False, server_default="0"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
