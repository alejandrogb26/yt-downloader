from datetime import UTC, datetime, timedelta
from socket import gethostname
from uuid import uuid4

from yt_downloader_api.core.config import Settings, get_settings
from yt_downloader_api.db.session import DatabaseConfigurationError, get_session_factory
from yt_downloader_api.repositories.download_queue import DownloadQueueRepository
from yt_downloader_api.services.download_queue import (
    DownloadQueue,
    DownloadQueuePersistenceError,
    claim_next_queued_job,
    mark_stale_running_jobs_as_failed,
)


def derive_worker_id(settings: Settings) -> str:
    if settings.worker_id:
        return settings.worker_id
    return f"yt-downloader-{gethostname()}-{uuid4().hex[:8]}"


def run_once(settings: Settings, repository: DownloadQueue) -> int:
    worker_id = derive_worker_id(settings)
    stale_before = datetime.now(UTC) - timedelta(
        seconds=settings.worker_stale_job_timeout_seconds
    )
    recovered_count = mark_stale_running_jobs_as_failed(repository, stale_before)
    job = claim_next_queued_job(repository, worker_id)
    if job is None:
        print(f"Recovered {recovered_count} stale job(s). No queued jobs available.")
        return 0
    print(f"Recovered {recovered_count} stale job(s). Job {job.id} marked as running.")
    return 0


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is required to run the worker.")
        return 1

    try:
        session_factory = get_session_factory()
        with session_factory() as session:
            repository = DownloadQueueRepository(session)
            return run_once(settings, repository)
    except DatabaseConfigurationError, DownloadQueuePersistenceError:
        print("Download worker cannot access the queue.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
