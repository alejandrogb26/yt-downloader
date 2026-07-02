import argparse
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from signal import SIG_DFL, SIGINT, SIGTERM, signal
from socket import gethostname
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yt_downloader_api.core.config import Settings, get_settings
from yt_downloader_api.db.models import DownloadJob, DownloadJobStatus
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
LOGGER_NAME = "yt_downloader_api.worker"

logger = logging.getLogger(LOGGER_NAME)


class WorkerInterrupted(Exception):
    """Raised when the worker receives a termination signal."""


class QueueDiagnosticSource(Protocol):
    def check_connection(self) -> None: ...

    def has_heartbeat_column(self) -> bool: ...

    def count_jobs_by_status(self) -> dict[str, int]: ...

    def check_repository(self) -> None: ...


class SqlAlchemyQueueDiagnosticSource:
    def __init__(self, session: Session) -> None:
        self.session = session

    def check_connection(self) -> None:
        self.session.execute(text("SELECT 1")).scalar_one()

    def has_heartbeat_column(self) -> bool:
        columns = {
            column["name"]
            for column in inspect(self.session.bind).get_columns("download_jobs")
        }
        return "heartbeat_at" in columns

    def count_jobs_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for status in DownloadJobStatus:
            count = self.session.scalar(
                select(func.count())
                .select_from(DownloadJob)
                .where(DownloadJob.status == status.value)
            )
            counts[status.value] = count or 0
        return counts

    def check_repository(self) -> None:
        self.session.scalar(select(func.count()).select_from(DownloadJob))


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
    try:
        recovered_count = mark_stale_running_jobs_as_failed(repository, stale_before)
    except DownloadQueuePersistenceError:
        log_queue_exception("recover stale running jobs")
        raise

    try:
        job = claim_next_queued_job(repository, worker_id)
    except DownloadQueuePersistenceError:
        log_queue_exception("claim next queued job")
        raise

    if job is None:
        print(f"Recovered {recovered_count} stale job(s). No queued jobs available.")
        return 0
    print(f"Recovered {recovered_count} stale job(s). Processing job {job.id}.")
    active_downloader = downloader or YtDlpAudioDownloader()
    active_executor = executor or execute_download_job
    try:
        add_running_job_event(
            repository,
            job.id,
            worker_id,
            "info",
            "Download started.",
        )
    except DownloadQueuePersistenceError:
        log_queue_exception("add download started event")
        raise

    try:
        completed = active_executor(
            settings,
            repository,
            active_downloader,
            job,
            worker_id,
        )
    except KeyboardInterrupt, WorkerInterrupted:
        try:
            mark_running_job_as_failed(
                repository,
                job.id,
                worker_id,
                INTERRUPTED_ERROR_CODE,
                INTERRUPTED_MESSAGE,
            )
        except DownloadQueuePersistenceError:
            log_queue_exception("mark interrupted job as failed")
            raise
        print(f"Job {job.id} interrupted.")
        return 1
    if completed:
        print(f"Job {job.id} completed.")
        return 0
    print(f"Job {job.id} failed.")
    return 1


def diagnose_queue(settings: Settings, session: Session) -> int:
    return diagnose_queue_source(settings, SqlAlchemyQueueDiagnosticSource(session))


def diagnose_queue_source(settings: Settings, source: QueueDiagnosticSource) -> int:
    if not settings.database_url:
        print("DATABASE_URL is required to diagnose the queue.")
        return 1

    try:
        source.check_connection()
        print("Database connection: OK")
        if not source.has_heartbeat_column():
            print("Queue schema: missing heartbeat_at")
            return 1
        print("Queue schema: OK")

        counts = source.count_jobs_by_status()
        for status in DownloadJobStatus:
            print(f"{status.value.capitalize()} jobs: {counts.get(status.value, 0)}")

        source.check_repository()
        print("Queue repository check: OK")
        print("Diagnosis mode is read-only; it does not claim jobs or run yt-dlp.")
        return 0
    except SQLAlchemyError, RuntimeError:
        logger.exception(
            "Queue diagnosis failed during read-only checks. exception_type=%s",
            type(get_current_exception()).__name__,
        )
        print("Download worker cannot access the queue.")
        return 1


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="yt-downloader worker")
    parser.add_argument(
        "--diagnose-queue",
        action="store_true",
        help="Run safe read-only queue diagnostics without downloading.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.database_url:
        if args.diagnose_queue:
            print("DATABASE_URL is required to diagnose the queue.")
        else:
            print("DATABASE_URL is required to run the worker.")
        return 1

    try:
        install_signal_handlers()
        session_factory = get_session_factory()
        with session_factory() as session:
            if args.diagnose_queue:
                return diagnose_queue(settings, session)
            repository = DownloadQueueRepository(session)
            return run_once(settings, repository)
    except DatabaseConfigurationError:
        logger.exception(
            "Worker database configuration failed. exception_type=%s",
            type(get_current_exception()).__name__,
        )
        print("Download worker cannot access the queue.")
        return 1
    except DownloadQueuePersistenceError:
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


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def log_queue_exception(operation: str) -> None:
    logger.exception(
        "Queue operation failed. operation=%s exception_type=%s",
        operation,
        type(get_current_exception()).__name__,
    )


def get_current_exception() -> BaseException:
    exception = sys.exc_info()[1]
    if exception is None:
        return RuntimeError("unknown error")
    return exception


if __name__ == "__main__":
    raise SystemExit(main())
