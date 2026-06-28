"""create download tables

Revision ID: 20260627_0001
Revises:
Create Date: 2026-06-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260627_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "download_jobs",
        sa.Column("id", mysql.CHAR(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "destination_relative_path",
            sa.String(length=1024),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "requested_format",
            sa.String(length=16),
            server_default="mp3",
            nullable=False,
        ),
        sa.Column("requested_audio_quality", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("progress_percent", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("output_relative_path", sa.String(length=1024), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column(
            "attempt_count",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_download_jobs")),
    )
    op.create_index(
        "ix_download_jobs_profile_id_created_at",
        "download_jobs",
        ["profile_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_download_jobs_status_created_at",
        "download_jobs",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "download_job_events",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("job_id", mysql.CHAR(length=36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.String(length=2048), nullable=False),
        sa.Column("progress_percent", mysql.INTEGER(unsigned=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["download_jobs.id"],
            name=op.f("fk_download_job_events_job_id_download_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_download_job_events")),
    )
    op.create_index(
        "ix_download_job_events_job_id_created_at",
        "download_job_events",
        ["job_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_download_job_events_job_id_created_at",
        table_name="download_job_events",
    )
    op.drop_table("download_job_events")
    op.drop_index("ix_download_jobs_status_created_at", table_name="download_jobs")
    op.drop_index("ix_download_jobs_profile_id_created_at", table_name="download_jobs")
    op.drop_table("download_jobs")
