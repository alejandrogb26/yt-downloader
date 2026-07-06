"""add download batches

Revision ID: 20260706_0005
Revises: 20260705_0004
Create Date: 2026-07-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260706_0005"
down_revision: str | None = "20260705_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "download_batches",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column(
            "default_destination_path",
            sa.String(length=1024),
            server_default="",
            nullable=False,
        ),
        sa.Column("total_items", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_download_batches_profile_id_created_at",
        "download_batches",
        ["profile_id", "created_at"],
    )
    op.add_column(
        "download_jobs",
        sa.Column("batch_id", sa.CHAR(length=36), nullable=True),
    )
    op.create_index(
        "ix_download_jobs_batch_id_created_at",
        "download_jobs",
        ["batch_id", "created_at"],
    )
    op.create_foreign_key(
        "fk_download_jobs_batch_id_download_batches",
        "download_jobs",
        "download_batches",
        ["batch_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_download_jobs_batch_id_download_batches",
        "download_jobs",
        type_="foreignkey",
    )
    op.drop_index("ix_download_jobs_batch_id_created_at", table_name="download_jobs")
    op.drop_column("download_jobs", "batch_id")
    op.drop_index(
        "ix_download_batches_profile_id_created_at",
        table_name="download_batches",
    )
    op.drop_table("download_batches")
