from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from yt_downloader_api.db.models import AudioPolicy, DownloadJob, DownloadJobStatus
from yt_downloader_api.models.profiles import LibraryProfile
from yt_downloader_api.repositories.download_jobs import DownloadJobRepositoryError


class DownloadPersistenceError(Exception):
    """Raised when a download job cannot be persisted safely."""


class DownloadJobWriter(Protocol):
    def create_queued_job_with_event(
        self,
        job: DownloadJob,
        created_at: datetime,
    ) -> DownloadJob: ...


@dataclass(frozen=True)
class CreatedDownloadJob:
    id: str
    profile: LibraryProfile
    source_url: str
    destination_path: str
    audio_policy: str
    status: str
    progress_percent: int | None
    title: str | None
    output_path: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def create_queued_download_job(
    repository: DownloadJobWriter,
    profile: LibraryProfile,
    source_url: str,
    destination_path: str,
) -> CreatedDownloadJob:
    now = datetime.now(UTC)
    job = DownloadJob(
        id=str(uuid4()),
        profile_id=profile.id,
        source_url=source_url,
        destination_relative_path=destination_path,
        audio_policy=AudioPolicy.PREFER_M4A_THEN_BEST_SOURCE.value,
        status=DownloadJobStatus.QUEUED.value,
        progress_percent=None,
        title=None,
        output_relative_path=None,
        source_format_id=None,
        source_container=None,
        source_audio_codec=None,
        output_container=None,
        output_audio_codec=None,
        transcode_applied=False,
        error_code=None,
        error_message=None,
        worker_id=None,
        attempt_count=0,
        created_at=now,
        updated_at=now,
        started_at=None,
        finished_at=None,
    )

    try:
        persisted_job = repository.create_queued_job_with_event(job, now)
    except DownloadJobRepositoryError as exc:
        raise DownloadPersistenceError from exc

    return CreatedDownloadJob(
        id=persisted_job.id,
        profile=profile,
        source_url=persisted_job.source_url,
        destination_path=persisted_job.destination_relative_path,
        audio_policy=persisted_job.audio_policy,
        status=persisted_job.status,
        progress_percent=persisted_job.progress_percent,
        title=persisted_job.title,
        output_path=persisted_job.output_relative_path,
        created_at=persisted_job.created_at,
        started_at=persisted_job.started_at,
        finished_at=persisted_job.finished_at,
    )
