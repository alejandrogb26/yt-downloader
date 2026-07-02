import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from yt_downloader_api.db.models import DownloadJob, DownloadJobStatus
from yt_downloader_api.repositories.download_queue import DownloadQueueRepositoryError
from yt_downloader_api.services.download_state import validate_status_transition


class DownloadQueuePersistenceError(Exception):
    """Raised when queue persistence fails safely."""


logger = logging.getLogger("yt_downloader_api.worker.queue")


@dataclass(frozen=True)
class CompletedDownloadJob:
    title: str
    output_relative_path: str
    source_format_id: str | None
    source_container: str | None
    source_audio_codec: str | None
    output_container: str | None
    output_audio_codec: str | None


class DownloadQueue(Protocol):
    def claim_next_queued_job(
        self,
        worker_id: str,
        claimed_at: datetime,
    ) -> DownloadJob | None: ...

    def mark_stale_running_jobs_as_failed(
        self,
        stale_before: datetime,
        failed_at: datetime,
    ) -> int: ...

    def touch_job_heartbeat(
        self,
        job_id: str,
        worker_id: str,
        touched_at: datetime,
    ) -> bool: ...

    def update_running_job_progress(
        self,
        job_id: str,
        worker_id: str,
        progress_percent: int | None,
        updated_at: datetime,
    ) -> bool: ...

    def add_running_job_event(
        self,
        job_id: str,
        worker_id: str,
        level: str,
        message: str,
        progress_percent: int | None,
        created_at: datetime,
    ) -> bool: ...

    def mark_running_job_as_completed(
        self,
        job_id: str,
        worker_id: str,
        completed: CompletedDownloadJob,
        completed_at: datetime,
    ) -> bool: ...

    def mark_running_job_as_failed(
        self,
        job_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        failed_at: datetime,
    ) -> bool: ...


def claim_next_queued_job(
    repository: DownloadQueue, worker_id: str
) -> DownloadJob | None:
    validate_status_transition(
        DownloadJobStatus.QUEUED.value,
        DownloadJobStatus.RUNNING.value,
    )
    try:
        return repository.claim_next_queued_job(worker_id, datetime.now(UTC))
    except DownloadQueueRepositoryError as exc:
        log_queue_exception("claim next queued job")
        raise DownloadQueuePersistenceError from exc


def mark_stale_running_jobs_as_failed(
    repository: DownloadQueue,
    stale_before: datetime,
) -> int:
    validate_status_transition(
        DownloadJobStatus.RUNNING.value,
        DownloadJobStatus.FAILED.value,
    )
    try:
        return repository.mark_stale_running_jobs_as_failed(
            stale_before,
            datetime.now(UTC),
        )
    except DownloadQueueRepositoryError as exc:
        log_queue_exception("recover stale running jobs")
        raise DownloadQueuePersistenceError from exc


def touch_job_heartbeat(repository: DownloadQueue, job_id: str, worker_id: str) -> bool:
    try:
        return repository.touch_job_heartbeat(job_id, worker_id, datetime.now(UTC))
    except DownloadQueueRepositoryError as exc:
        log_queue_exception("update heartbeat")
        raise DownloadQueuePersistenceError from exc


def update_running_job_progress(
    repository: DownloadQueue,
    job_id: str,
    worker_id: str,
    progress_percent: int | None,
) -> bool:
    try:
        return repository.update_running_job_progress(
            job_id,
            worker_id,
            progress_percent,
            datetime.now(UTC),
        )
    except DownloadQueueRepositoryError as exc:
        log_queue_exception("update progress and heartbeat")
        raise DownloadQueuePersistenceError from exc


def add_running_job_event(
    repository: DownloadQueue,
    job_id: str,
    worker_id: str,
    level: str,
    message: str,
    progress_percent: int | None = None,
) -> bool:
    try:
        return repository.add_running_job_event(
            job_id,
            worker_id,
            level,
            message,
            progress_percent,
            datetime.now(UTC),
        )
    except DownloadQueueRepositoryError as exc:
        log_queue_exception("add running job event")
        raise DownloadQueuePersistenceError from exc


def mark_running_job_as_completed(
    repository: DownloadQueue,
    job_id: str,
    worker_id: str,
    completed: CompletedDownloadJob,
) -> bool:
    validate_status_transition(
        DownloadJobStatus.RUNNING.value,
        DownloadJobStatus.COMPLETED.value,
    )
    try:
        return repository.mark_running_job_as_completed(
            job_id,
            worker_id,
            completed,
            datetime.now(UTC),
        )
    except DownloadQueueRepositoryError as exc:
        log_queue_exception("mark running job as completed")
        raise DownloadQueuePersistenceError from exc


def mark_running_job_as_failed(
    repository: DownloadQueue,
    job_id: str,
    worker_id: str,
    error_code: str,
    error_message: str,
) -> bool:
    validate_status_transition(
        DownloadJobStatus.RUNNING.value,
        DownloadJobStatus.FAILED.value,
    )
    try:
        return repository.mark_running_job_as_failed(
            job_id,
            worker_id,
            error_code,
            error_message,
            datetime.now(UTC),
        )
    except DownloadQueueRepositoryError as exc:
        log_queue_exception("mark running job as failed")
        raise DownloadQueuePersistenceError from exc


def log_queue_exception(operation: str) -> None:
    logger.exception(
        "Queue operation failed. operation=%s exception_type=%s",
        operation,
        type(get_current_exception()).__name__,
    )


def get_current_exception() -> BaseException:
    import sys

    exception = sys.exc_info()[1]
    if exception is None:
        return RuntimeError("unknown error")
    return exception
