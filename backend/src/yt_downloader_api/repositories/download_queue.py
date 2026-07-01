from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yt_downloader_api.db.models import DownloadJob, DownloadJobEvent, DownloadJobStatus

CLAIMED_EVENT_MESSAGE = "Download job claimed by worker."
INTERRUPTED_ERROR_CODE = "worker_interrupted"
INTERRUPTED_MESSAGE = "Download worker stopped before completion."


class DownloadQueueRepositoryError(Exception):
    """Raised when queue persistence fails."""


class DownloadQueueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def claim_next_queued_job(
        self, worker_id: str, claimed_at: datetime
    ) -> DownloadJob | None:
        try:
            with self.session.begin():
                job = self.session.scalars(
                    select(DownloadJob)
                    .where(DownloadJob.status == DownloadJobStatus.QUEUED.value)
                    .order_by(DownloadJob.created_at.asc(), DownloadJob.id.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                ).first()
                if job is None:
                    return None

                job.status = DownloadJobStatus.RUNNING.value
                job.worker_id = worker_id
                job.attempt_count += 1
                if job.started_at is None:
                    job.started_at = claimed_at
                job.updated_at = claimed_at
                job.heartbeat_at = claimed_at
                self.session.add(
                    DownloadJobEvent(
                        job_id=job.id,
                        created_at=claimed_at,
                        level="info",
                        message=CLAIMED_EVENT_MESSAGE,
                        progress_percent=None,
                    )
                )
            return job
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadQueueRepositoryError from exc

    def mark_stale_running_jobs_as_failed(
        self,
        stale_before: datetime,
        failed_at: datetime,
    ) -> int:
        try:
            stale_jobs = list(
                self.session.scalars(
                    select(DownloadJob)
                    .where(DownloadJob.status == DownloadJobStatus.RUNNING.value)
                    .where(
                        or_(
                            DownloadJob.heartbeat_at.is_(None),
                            DownloadJob.heartbeat_at < stale_before,
                        )
                    )
                    .order_by(DownloadJob.created_at.asc(), DownloadJob.id.asc())
                ).all()
            )
            count = 0
            for job in stale_jobs:
                job.status = DownloadJobStatus.FAILED.value
                job.finished_at = failed_at
                job.updated_at = failed_at
                job.error_code = INTERRUPTED_ERROR_CODE
                job.error_message = INTERRUPTED_MESSAGE
                self.session.add(
                    DownloadJobEvent(
                        job_id=job.id,
                        created_at=failed_at,
                        level="error",
                        message=INTERRUPTED_MESSAGE,
                        progress_percent=None,
                    )
                )
                self.session.commit()
                count += 1
            return count
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadQueueRepositoryError from exc

    def touch_job_heartbeat(
        self,
        job_id: str,
        worker_id: str,
        touched_at: datetime,
    ) -> bool:
        try:
            with self.session.begin():
                job = self.session.get(DownloadJob, job_id)
                if (
                    job is None
                    or job.status != DownloadJobStatus.RUNNING.value
                    or job.worker_id != worker_id
                ):
                    return False
                job.heartbeat_at = touched_at
                job.updated_at = touched_at
            return True
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadQueueRepositoryError from exc
