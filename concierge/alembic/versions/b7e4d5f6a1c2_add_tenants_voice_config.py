"""add tenants.voice_config (D2 structured voice schema)

Revision ID: b7e4d5f6a1c2
Revises: a6f2b1c3d4e5
Create Date: 2026-09-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7e4d5f6a1c2"
down_revision: Union[str, None] = "a6f2b1c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # D2: structured per-tenant voice config. The Tenant model gained this
    # column without a migration — without it, inserting a tenant fails on any
    # migrated DB.
    op.add_column(
        "tenants",
        sa.Column(
            "voice_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "voice_config")