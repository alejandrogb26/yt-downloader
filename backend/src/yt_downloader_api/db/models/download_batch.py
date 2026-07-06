from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Index, String
from sqlalchemy.dialects.mysql import CHAR, DATETIME, INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yt_downloader_api.db.base import Base
from yt_downloader_api.db.models.download_job import utc_now

if TYPE_CHECKING:
    from yt_downloader_api.db.models.download_job import DownloadJob


class DownloadBatch(Base):
    __tablename__ = "download_batches"
    __table_args__ = (
        Index("ix_download_batches_profile_id_created_at", "profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    default_destination_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        default="",
        server_default="",
    )
    total_items: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        default=utc_now,
    )

    jobs: Mapped[list[DownloadJob]] = relationship(back_populates="batch")
