from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yt_downloader_api.db.base import Base
from yt_downloader_api.db.models.download_job import DownloadJob, utc_now


class DownloadJobEvent(Base):
    __tablename__ = "download_job_events"
    __table_args__ = (
        Index("ix_download_job_events_job_id_created_at", "job_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
    )
    job_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("download_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        default=utc_now,
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(2048), nullable=False)
    progress_percent: Mapped[int | None] = mapped_column(INTEGER(unsigned=True))

    job: Mapped[DownloadJob] = relationship(back_populates="events")
