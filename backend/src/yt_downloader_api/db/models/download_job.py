from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Index, String, Text, false
from sqlalchemy.dialects.mysql import CHAR, DATETIME, INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression

from yt_downloader_api.db.base import Base

if TYPE_CHECKING:
    from yt_downloader_api.db.models.download_job_event import DownloadJobEvent


class DownloadJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AudioPolicy(StrEnum):
    PREFER_M4A_THEN_BEST_SOURCE = "prefer_m4a_then_best_source"


def utc_now() -> datetime:
    return datetime.now(UTC)


class DownloadJob(Base):
    __tablename__ = "download_jobs"
    __table_args__ = (
        Index("ix_download_jobs_status_created_at", "status", "created_at"),
        Index("ix_download_jobs_profile_id_created_at", "profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    destination_relative_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        default="",
        server_default="",
    )
    audio_policy: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=AudioPolicy.PREFER_M4A_THEN_BEST_SOURCE.value,
        server_default=AudioPolicy.PREFER_M4A_THEN_BEST_SOURCE.value,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DownloadJobStatus.QUEUED.value,
        server_default=DownloadJobStatus.QUEUED.value,
    )
    progress_percent: Mapped[int | None] = mapped_column(INTEGER(unsigned=True))
    title: Mapped[str | None] = mapped_column(String(512))
    output_relative_path: Mapped[str | None] = mapped_column(String(1024))
    source_format_id: Mapped[str | None] = mapped_column(String(64))
    source_container: Mapped[str | None] = mapped_column(String(16))
    source_audio_codec: Mapped[str | None] = mapped_column(String(32))
    output_container: Mapped[str | None] = mapped_column(String(16))
    output_audio_codec: Mapped[str | None] = mapped_column(String(32))
    transcode_applied: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    attempt_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True),
        nullable=False,
        default=0,
        server_default=expression.text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))

    events: Mapped[list[DownloadJobEvent]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
