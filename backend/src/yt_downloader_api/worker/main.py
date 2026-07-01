from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from signal import SIG_DFL, SIGINT, SIGTERM, signal
from socket import gethostname
from uuid import uuid4

from yt_downloader_api.core.config import Settings, get_settings
from yt_downloader_api.db.session import DatabaseConfigurationError, get_session_factory
from yt_downloader_api.downloaders.base import AudioDownloader
from yt_downloader_api.downloaders.yt_dlp_downloader import YtDlpAudioDownloader
from yt_downloader_api.repositories.download_queue import DownloadQueueRepository
from yt_downloader_api.services.download_execution import execute_download_job
from yt_downloader_api.services.download_queue import (
    DownloadQueue,
    DownloadQueuePersistenceError,
    add_running_job_event,
    claim_next_queued_job,
    mark_running_job_as_failed,
    mark_stale_running_jobs_as_failed,
)

INTERRUPTED_ERROR_CODE = "worker_interrupted"
INTERRUPTED_MESSAGE = "Download worker stopped before completion."


class WorkerInterrupted(Exception):
    """Raised when the worker receives a termination signal."""


def derive_worker_id(settings: Settings) -> str:
    if settings.worker_id:
        return settings.worker_id
    return f"yt-downloader-{gethostname()}-{uuid4().hex[:8]}"


def run_once(
    settings: Settings,
    repository: DownloadQueue,
    downloader: AudioDownloader | None = None,
    executor: Callable[[Settings, DownloadQueue, AudioDownloader, object, str], bool]
    | None = None,
) -> int:
    worker_id = derive_worker_id(settings)
    stale_before = datetime.now(UTC) - timedelta(
        seconds=settings.worker_stale_job_timeout_seconds
    )
    recovered_count = mark_stale_running_jobs_as_failed(repository, stale_before)
    job = claim_next_queued_job(repository, worker_id)
    if job is None:
        print(f"Recovered {recovered_count} stale job(s). No queued jobs available.")
        return 0
    print(f"Recovered {recovered_count} stale job(s). Processing job {job.id}.")
    active_downloader = downloader or YtDlpAudioDownloader()
    active_executor = executor or execute_download_job
    add_running_job_event(
        repository,
        job.id,
        worker_id,
        "info",
        "Download started.",
    )
    try:
        completed = active_executor(
            settings,
            repository,
            active_downloader,
            job,
            worker_id,
        )
    except KeyboardInterrupt, WorkerInterrupted:
        mark_running_job_as_failed(
            repository,
            job.id,
            worker_id,
            INTERRUPTED_ERROR_CODE,
            INTERRUPTED_MESSAGE,
        )
        print(f"Job {job.id} interrupted.")
        return 1
    if completed:
        print(f"Job {job.id} completed.")
        return 0
    print(f"Job {job.id} failed.")
    return 1


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is required to run the worker.")
        return 1

    try:
        install_signal_handlers()
        session_factory = get_session_factory()
        with session_factory() as session:
            repository = DownloadQueueRepository(session)
            return run_once(settings, repository)
    except DatabaseConfigurationError, DownloadQueuePersistenceError:
        print("Download worker cannot access the queue.")
        return 1


def install_signal_handlers() -> None:
    def raise_interrupted(_signum: int, _frame: object) -> None:
        raise WorkerInterrupted

    signal(SIGINT, raise_interrupted)
    signal(SIGTERM, raise_interrupted)


def restore_default_signal_handlers() -> None:
    signal(SIGINT, SIG_DFL)
    signal(SIGTERM, SIG_DFL)


if __name__ == "__main__":
    raise SystemExit(main())
