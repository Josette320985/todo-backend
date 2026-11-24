"""Migrate primary and foreign keys from Integer to Uuid.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # On SQLite, PRAGMA foreign_keys=OFF is set by run_migrations (OPT-05).
    # Rebuild tasks table with Uuid id and owner_id.
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column(
            "id",
            existing_type=sa.Integer(),
            type_=sa.Uuid(),
            existing_nullable=False,
        )
        batch.alter_column(
            "owner_id",
            existing_type=sa.Integer(),
            type_=sa.Uuid(),
            existing_nullable=False,
        )

    # Rebuild users table with Uuid id.
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "id",
            existing_type=sa.Integer(),
            type_=sa.Uuid(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column(
            "id",
            existing_type=sa.Uuid(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
        batch.alter_column(
            "owner_id",
            existing_type=sa.Uuid(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "id",
            existing_type=sa.Uuid(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
