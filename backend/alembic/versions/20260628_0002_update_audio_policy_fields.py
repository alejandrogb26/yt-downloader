"""update audio policy fields

Revision ID: 20260628_0002
Revises: 20260627_0001
Create Date: 2026-06-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260628_0002"
down_revision: str | None = "20260627_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_AUDIO_POLICY = "prefer_m4a_then_best_source"


def upgrade() -> None:
    op.alter_column(
        "download_jobs",
        "requested_format",
        new_column_name="audio_policy",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
        existing_server_default="mp3",
        server_default=NEW_AUDIO_POLICY,
    )
    op.drop_column("download_jobs", "requested_audio_quality")
    op.add_column(
        "download_jobs",
        sa.Column("source_format_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "download_jobs",
        sa.Column("source_container", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "download_jobs",
        sa.Column("source_audio_codec", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "download_jobs",
        sa.Column("output_container", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "download_jobs",
        sa.Column("output_audio_codec", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "download_jobs",
        sa.Column(
            "transcode_applied",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("download_jobs", "transcode_applied")
    op.drop_column("download_jobs", "output_audio_codec")
    op.drop_column("download_jobs", "output_container")
    op.drop_column("download_jobs", "source_audio_codec")
    op.drop_column("download_jobs", "source_container")
    op.drop_column("download_jobs", "source_format_id")
    op.add_column(
        "download_jobs",
        sa.Column("requested_audio_quality", sa.String(length=32), nullable=True),
    )
    op.alter_column(
        "download_jobs",
        "audio_policy",
        new_column_name="requested_format",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=NEW_AUDIO_POLICY,
        server_default="mp3",
    )
