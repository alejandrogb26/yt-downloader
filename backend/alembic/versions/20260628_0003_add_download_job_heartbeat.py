"""add download job heartbeat

Revision ID: 20260628_0003
Revises: 20260628_0002
Create Date: 2026-06-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260628_0003"
down_revision: str | None = "20260628_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "download_jobs",
        sa.Column("heartbeat_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    op.create_index(
        "ix_download_jobs_status_heartbeat_at",
        "download_jobs",
        ["status", "heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_download_jobs_status_heartbeat_at", table_name="download_jobs")
    op.drop_column("download_jobs", "heartbeat_at")
