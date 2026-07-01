from datetime import UTC, datetime
from typing import Protocol

from yt_downloader_api.db.models import DownloadJob, DownloadJobStatus
from yt_downloader_api.repositories.download_queue import DownloadQueueRepositoryError
from yt_downloader_api.services.download_state import validate_status_transition


class DownloadQueuePersistenceError(Exception):
    """Raised when queue persistence fails safely."""


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
        raise DownloadQueuePersistenceError from exc


def touch_job_heartbeat(repository: DownloadQueue, job_id: str, worker_id: str) -> bool:
    try:
        return repository.touch_job_heartbeat(job_id, worker_id, datetime.now(UTC))
    except DownloadQueueRepositoryError as exc:
        raise DownloadQueuePersistenceError from exc
