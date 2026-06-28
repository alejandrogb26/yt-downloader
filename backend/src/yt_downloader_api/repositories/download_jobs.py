from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yt_downloader_api.db.models import DownloadJob, DownloadJobEvent


class DownloadJobRepositoryError(Exception):
    """Raised when download job persistence fails."""


class DownloadJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_queued_job_with_event(
        self,
        job: DownloadJob,
        created_at: datetime,
    ) -> DownloadJob:
        event = DownloadJobEvent(
            job_id=job.id,
            created_at=created_at,
            level="info",
            message="Download job queued.",
            progress_percent=None,
        )
        try:
            self.session.add(job)
            self.session.add(event)
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadJobRepositoryError from exc
        return job
