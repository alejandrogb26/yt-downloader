from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yt_downloader_api.db.models import DownloadJob, DownloadJobEvent, DownloadJobStatus

if TYPE_CHECKING:
    from yt_downloader_api.services.download_queue import CompletedDownloadJob

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
            with self.session.begin():
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
            return len(stale_jobs)
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

    def update_running_job_progress(
        self,
        job_id: str,
        worker_id: str,
        progress_percent: int | None,
        updated_at: datetime,
    ) -> bool:
        try:
            with self.session.begin():
                job = self.session.get(DownloadJob, job_id)
                if not is_current_running_job(job, worker_id):
                    return False
                job.progress_percent = progress_percent
                job.heartbeat_at = updated_at
                job.updated_at = updated_at
            return True
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadQueueRepositoryError from exc

    def add_running_job_event(
        self,
        job_id: str,
        worker_id: str,
        level: str,
        message: str,
        progress_percent: int | None,
        created_at: datetime,
    ) -> bool:
        try:
            with self.session.begin():
                job = self.session.get(DownloadJob, job_id)
                if not is_current_running_job(job, worker_id):
                    return False
                self.session.add(
                    DownloadJobEvent(
                        job_id=job_id,
                        created_at=created_at,
                        level=level,
                        message=message,
                        progress_percent=progress_percent,
                    )
                )
            return True
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadQueueRepositoryError from exc

    def mark_running_job_as_completed(
        self,
        job_id: str,
        worker_id: str,
        completed: CompletedDownloadJob,
        completed_at: datetime,
    ) -> bool:
        try:
            with self.session.begin():
                job = self.session.get(DownloadJob, job_id)
                if not is_current_running_job(job, worker_id):
                    return False
                job.status = DownloadJobStatus.COMPLETED.value
                job.progress_percent = 100
                job.title = completed.title
                job.output_relative_path = completed.output_relative_path
                job.source_format_id = completed.source_format_id
                job.source_container = completed.source_container
                job.source_audio_codec = completed.source_audio_codec
                job.output_container = completed.output_container
                job.output_audio_codec = completed.output_audio_codec
                job.transcode_applied = False
                job.updated_at = completed_at
                job.heartbeat_at = completed_at
                job.finished_at = completed_at
                self.session.add(
                    DownloadJobEvent(
                        job_id=job_id,
                        created_at=completed_at,
                        level="info",
                        message="Download completed.",
                        progress_percent=100,
                    )
                )
            return True
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadQueueRepositoryError from exc

    def mark_running_job_as_failed(
        self,
        job_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        failed_at: datetime,
    ) -> bool:
        try:
            with self.session.begin():
                job = self.session.get(DownloadJob, job_id)
                if not is_current_running_job(job, worker_id):
                    return False
                job.status = DownloadJobStatus.FAILED.value
                job.error_code = error_code
                job.error_message = error_message
                job.updated_at = failed_at
                job.finished_at = failed_at
                self.session.add(
                    DownloadJobEvent(
                        job_id=job_id,
                        created_at=failed_at,
                        level="error",
                        message=error_message,
                        progress_percent=None,
                    )
                )
            return True
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadQueueRepositoryError from exc


def is_current_running_job(job: DownloadJob | None, worker_id: str) -> bool:
    return (
        job is not None
        and job.status == DownloadJobStatus.RUNNING.value
        and job.worker_id == worker_id
    )
