import logging
import os
import re
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Any, Protocol

from yt_downloader_api.core.config import Settings
from yt_downloader_api.downloaders.base import (
    AudioDownloader,
    AudioDownloadResult,
    DownloadAdapterError,
)
from yt_downloader_api.models.profiles import LibraryProfile
from yt_downloader_api.services import filesystem
from yt_downloader_api.services.download_queue import (
    CompletedDownloadJob,
    DownloadQueue,
    add_running_job_event,
    mark_running_job_as_completed,
    mark_running_job_as_failed,
    update_running_job_progress,
)
from yt_downloader_api.services.filenames import (
    InvalidRequestedFilenameError,
    validate_requested_filename,
)
from yt_downloader_api.services.profiles import (
    ProfilesConfigurationError,
    load_enabled_profile,
    load_profiles_config,
)

DOWNLOAD_FAILED_MESSAGE = "Audio download failed."
DOWNLOAD_RETRIES_EXHAUSTED_MESSAGE = (
    "No se pudo descargar el audio tras {attempts} intentos."
)
DOWNLOAD_INTERRUPTED_MESSAGE = "El worker se detuvo antes de completar la descarga."
DESTINATION_FAILED_MESSAGE = "Download destination is unavailable."
DESTINATION_WRITE_FAILED_MESSAGE = "Downloaded file could not be saved."
LOGGER = logging.getLogger("yt_downloader_api.worker.download_execution")


class DownloadExecutionError(Exception):
    """Raised when a download job cannot be completed safely."""


class DownloadRetryInterrupted(Exception):
    """Raised when worker shutdown interrupts retry backoff."""


class DownloadJobData(Protocol):
    id: str
    profile_id: str
    source_url: str
    destination_relative_path: str
    requested_filename: str | None


@dataclass(frozen=True)
class PublishedDownload:
    relative_path: str
    final_path: Path


class ProgressReporter:
    def __init__(
        self,
        repository: DownloadQueue,
        job_id: str,
        worker_id: str,
        interval_seconds: int,
        minimum_percent_delta: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.job_id = job_id
        self.worker_id = worker_id
        self.interval = timedelta(seconds=max(interval_seconds, 0))
        self.minimum_percent_delta = max(minimum_percent_delta, 0)
        self.now = now or (lambda: datetime.now(UTC))
        self.last_written_at: datetime | None = None
        self.last_written_percent: int | None = None

    def __call__(self, progress: dict[str, Any]) -> None:
        status = progress.get("status")
        percent = calculate_progress_percent(progress)
        current_time = self.now()
        if not self.should_write(status, percent, current_time):
            return
        update_running_job_progress(
            self.repository,
            self.job_id,
            self.worker_id,
            percent,
        )
        self.last_written_at = current_time
        self.last_written_percent = percent

    def should_write(
        self,
        status: object,
        percent: int | None,
        current_time: datetime,
    ) -> bool:
        if status == "finished":
            return True
        if self.last_written_at is None:
            return True
        if percent is not None and self.last_written_percent is not None:
            if percent - self.last_written_percent >= self.minimum_percent_delta:
                return True
        if percent is not None and self.last_written_percent is None:
            return True
        return current_time - self.last_written_at >= self.interval


def execute_download_job(
    settings: Settings,
    repository: DownloadQueue,
    downloader: AudioDownloader,
    job: DownloadJobData,
    worker_id: str,
    backoff_wait: Callable[[int], bool] | None = None,
) -> bool:
    staging_directory = Path(settings.download_staging_root) / job.id
    wait_for_retry = backoff_wait or default_backoff_wait
    try:
        validate_staging_root(settings)
        progress_reporter = ProgressReporter(
            repository,
            job.id,
            worker_id,
            settings.download_progress_update_interval_seconds,
            settings.download_progress_minimum_percent_delta,
        )
        result = download_audio_with_retries(
            settings,
            repository,
            downloader,
            job,
            worker_id,
            staging_directory,
            progress_reporter,
            wait_for_retry,
        )
        add_running_job_event(
            repository,
            job.id,
            worker_id,
            "info",
            "Audio download finished. Moving file to library.",
        )
        profile = get_current_profile(settings, job.profile_id)
        published = publish_download_to_library(profile, job, result)
        completed = CompletedDownloadJob(
            title=result.title,
            output_relative_path=published.relative_path,
            source_format_id=result.source_format_id,
            source_container=result.source_container,
            source_audio_codec=result.source_audio_codec,
            output_container=result.output_container,
            output_audio_codec=result.output_audio_codec,
        )
        return mark_running_job_as_completed(repository, job.id, worker_id, completed)
    except DownloadRetryInterrupted:
        mark_running_job_as_failed(
            repository,
            job.id,
            worker_id,
            "worker_interrupted",
            DOWNLOAD_INTERRUPTED_MESSAGE,
        )
        return False
    except DownloadAdapterError:
        message = DOWNLOAD_RETRIES_EXHAUSTED_MESSAGE.format(
            attempts=settings.yt_dlp_max_attempts
        )
        mark_running_job_as_failed(
            repository,
            job.id,
            worker_id,
            "download_failed",
            message,
        )
        return False
    except (
        ProfilesConfigurationError,
        filesystem.DirectoryNotFoundError,
        filesystem.InvalidDirectoryPathError,
        filesystem.ProfileStorageUnavailableError,
        filesystem.RequestedDirectoryNotAllowedError,
        filesystem.RequestedPathNotDirectoryError,
        StagingConfigurationError,
    ):
        mark_running_job_as_failed(
            repository,
            job.id,
            worker_id,
            "destination_unavailable",
            DESTINATION_FAILED_MESSAGE,
        )
        return False
    except OSError:
        mark_running_job_as_failed(
            repository,
            job.id,
            worker_id,
            "destination_write_failed",
            DESTINATION_WRITE_FAILED_MESSAGE,
        )
        return False
    finally:
        cleanup_staging_directory(staging_directory)


def download_audio_with_retries(
    settings: Settings,
    repository: DownloadQueue,
    downloader: AudioDownloader,
    job: DownloadJobData,
    worker_id: str,
    staging_directory: Path,
    progress_reporter: ProgressReporter,
    backoff_wait: Callable[[int], bool],
) -> AudioDownloadResult:
    max_attempts = settings.yt_dlp_max_attempts
    for attempt_number in range(1, max_attempts + 1):
        try:
            return downloader.download_audio(
                job.source_url,
                job.id,
                staging_directory,
                progress_reporter,
            )
        except DownloadAdapterError:
            LOGGER.exception(
                "yt-dlp download attempt failed. "
                "phase=yt_dlp_download job_id=%s batch_id=%s "
                "attempt=%s max_attempts=%s",
                job.id,
                getattr(job, "batch_id", None),
                attempt_number,
                max_attempts,
            )
            cleanup_staging_directory(staging_directory)
            if attempt_number >= max_attempts:
                raise
            delay_seconds = retry_delay_seconds(
                settings.yt_dlp_retry_initial_delay_seconds,
                attempt_number,
            )
            retry_attempt_number = attempt_number + 1
            event_recorded = add_running_job_event(
                repository,
                job.id,
                worker_id,
                "warning",
                "La descarga falló. "
                f"Reintentando ({retry_attempt_number} de {max_attempts}) "
                f"en {delay_seconds} segundos.",
            )
            if not event_recorded:
                raise
            if backoff_wait(delay_seconds):
                raise DownloadRetryInterrupted from None
    raise DownloadAdapterError("Audio download failed.")


def retry_delay_seconds(initial_delay_seconds: int, completed_attempts: int) -> int:
    return initial_delay_seconds * (2 ** (completed_attempts - 1))


def default_backoff_wait(delay_seconds: int) -> bool:
    sleep(delay_seconds)
    return False


class StagingConfigurationError(Exception):
    """Raised when staging is not safely separated from libraries."""


def validate_staging_root(settings: Settings) -> None:
    staging_root = Path(settings.download_staging_root)
    if not staging_root.is_absolute():
        raise StagingConfigurationError
    profiles_config = load_profiles_config(settings.profiles_config_path)
    staging_resolved = staging_root.resolve(strict=False)
    for profile in profiles_config.profiles:
        library_root = Path(profile.root_path).resolve(strict=False)
        if staging_resolved == library_root:
            raise StagingConfigurationError
        try:
            staging_resolved.relative_to(library_root)
        except ValueError:
            continue
        raise StagingConfigurationError


def get_current_profile(settings: Settings, profile_id: str) -> LibraryProfile:
    profile = load_enabled_profile(settings.profiles_config_path, profile_id)
    if profile is None:
        raise filesystem.ProfileStorageUnavailableError
    return profile


def publish_download_to_library(
    profile: LibraryProfile,
    job: DownloadJobData,
    result: AudioDownloadResult,
) -> PublishedDownload:
    source_path = validate_staged_file(result.downloaded_file_path, job.id)
    root = Path(profile.root_path)
    filesystem.ensure_writable_root(root)
    target_directory_path = filesystem.validate_relative_directory_path(
        job.destination_relative_path
    )
    target_directory = filesystem.resolve_target_directory(root, target_directory_path)
    filename = build_download_filename(
        job,
        result,
        source_path.suffix.removeprefix("."),
    )
    temporary_path = target_directory / f".{job.id}.part"
    final_path = copy_and_publish_file(
        source_path, target_directory, temporary_path, filename
    )
    return PublishedDownload(
        relative_path=filesystem.join_relative_path(
            target_directory_path, final_path.name
        ),
        final_path=final_path,
    )


def validate_staged_file(path: Path, job_id: str) -> Path:
    try:
        path_status = path.stat(follow_symlinks=False)
    except OSError:
        raise
    if path.is_symlink() or not stat.S_ISREG(path_status.st_mode):
        raise OSError("Invalid staged file")
    if path.parent.name != job_id:
        raise OSError("Invalid staged file")
    return path


def copy_and_publish_file(
    source_path: Path,
    target_directory: Path,
    temporary_path: Path,
    filename: str,
) -> Path:
    try:
        with source_path.open("rb") as source_file:
            with temporary_path.open("xb") as temporary_file:
                shutil.copyfileobj(source_file, temporary_file)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
        sync_directory(target_directory)
        for candidate in iter_collision_filenames(target_directory, filename):
            try:
                os.link(temporary_path, candidate)
            except FileExistsError:
                continue
            try:
                temporary_path.unlink()
            finally:
                sync_directory(target_directory)
            return candidate
        raise OSError("Could not publish downloaded file")
    except OSError:
        cleanup_path(temporary_path)
        raise


def iter_collision_filenames(target_directory: Path, filename: str):
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    yield target_directory / filename
    for index in range(1, 1000):
        yield target_directory / f"{stem} ({index}){suffix}"


def build_download_filename(
    job: DownloadJobData,
    result: AudioDownloadResult,
    extension: str,
) -> str:
    if job.requested_filename is not None:
        return build_requested_download_filename(job.requested_filename, extension)
    return build_safe_download_filename(result.title, result.video_id, extension)


def build_requested_download_filename(requested_filename: str, extension: str) -> str:
    try:
        safe_name = validate_requested_filename(requested_filename)
    except InvalidRequestedFilenameError as exc:
        raise OSError("Invalid requested filename") from exc
    if safe_name is None:
        raise OSError("Invalid requested filename")
    return f"{safe_name}.{sanitize_extension(extension)}"


def build_safe_download_filename(title: str, video_id: str, extension: str) -> str:
    safe_title = sanitize_filename_component(title) or "audio"
    safe_video_id = sanitize_filename_component(video_id) or "audio"
    safe_extension = sanitize_extension(extension)
    suffix = f" [{safe_video_id}].{safe_extension}"
    max_title_length = max(1, 180 - len(suffix))
    return f"{safe_title[:max_title_length].rstrip()}{suffix}"


def sanitize_filename_component(value: str) -> str:
    cleaned = re.sub(r"[/\\\x00-\x1f\x7f]", " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.lstrip(".").strip()
    return cleaned[:120]


def sanitize_extension(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value).lower()
    return cleaned or "audio"


def calculate_progress_percent(progress: dict[str, Any]) -> int | None:
    downloaded_bytes = progress.get("downloaded_bytes")
    total_bytes = progress.get("total_bytes") or progress.get("total_bytes_estimate")
    if not isinstance(downloaded_bytes, int | float):
        return None
    if not isinstance(total_bytes, int | float) or total_bytes <= 0:
        return None
    percent = int((downloaded_bytes / total_bytes) * 100)
    return max(0, min(100, percent))


def sync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def cleanup_staging_directory(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def cleanup_path(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
