"""Add users.auth_provider (F1 LDAP).

Existing rows stay "local". Directory accounts created after this migration
store "ldap" and a random password hash they cannot use to log in locally.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "auth_provider",
                sa.String(length=16),
                nullable=False,
                server_default="local",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("auth_provider")
