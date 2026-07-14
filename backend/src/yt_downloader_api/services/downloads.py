from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from yt_downloader_api.db.models import (
    AudioPolicy,
    DownloadBatch,
    DownloadJob,
    DownloadJobEvent,
    DownloadJobStatus,
)
from yt_downloader_api.models.profiles import LibraryProfile
from yt_downloader_api.repositories.download_jobs import DownloadJobRepositoryError


class DownloadPersistenceError(Exception):
    """Raised when a download job cannot be persisted safely."""


class DownloadJobNotFoundError(Exception):
    """Raised when a download job does not exist."""


class InvalidDownloadJobIdError(Exception):
    """Raised when a download job ID is not a UUID v4 string."""


class DownloadJobWriter(Protocol):
    def create_queued_job_with_event(
        self,
        job: DownloadJob,
        created_at: datetime,
    ) -> DownloadJob: ...

    def create_batch_with_jobs_and_events(
        self,
        batch: DownloadBatch,
        jobs: list[DownloadJob],
        created_at: datetime,
    ) -> DownloadBatch: ...

    def list_jobs(
        self,
        limit: int,
        offset: int,
        profile_id: str | None = None,
        status: str | None = None,
        batch_id: str | None = None,
        profile_ids: set[str] | None = None,
    ) -> tuple[list[DownloadJob], int]: ...

    def get_job(self, job_id: str) -> DownloadJob | None: ...

    def list_events(
        self,
        job_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[DownloadJobEvent], int]: ...

    def list_batches(
        self,
        profile_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[DownloadBatch], int]: ...

    def get_batch(self, batch_id: str) -> DownloadBatch | None: ...


@dataclass(frozen=True)
class CreatedDownloadJob:
    id: str
    profile: LibraryProfile
    source_url: str
    destination_path: str
    requested_filename: str | None
    audio_policy: str
    status: str
    progress_percent: int | None
    title: str | None
    output_path: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class DownloadBatchItemInput:
    source_url: str
    destination_path: str
    requested_filename: str | None


@dataclass(frozen=True)
class CreatedDownloadBatch:
    batch: DownloadBatch
    jobs: list[DownloadJob]


def create_queued_download_job(
    repository: DownloadJobWriter,
    profile: LibraryProfile,
    source_url: str,
    destination_path: str,
    requested_filename: str | None = None,
) -> CreatedDownloadJob:
    now = datetime.now(UTC)
    job = DownloadJob(
        id=str(uuid4()),
        profile_id=profile.id,
        source_url=source_url,
        destination_relative_path=destination_path,
        requested_filename=requested_filename,
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
        requested_filename=persisted_job.requested_filename,
        audio_policy=persisted_job.audio_policy,
        status=persisted_job.status,
        progress_percent=persisted_job.progress_percent,
        title=persisted_job.title,
        output_path=persisted_job.output_relative_path,
        created_at=persisted_job.created_at,
        started_at=persisted_job.started_at,
        finished_at=persisted_job.finished_at,
    )


def create_queued_download_batch(
    repository: DownloadJobWriter,
    profile: LibraryProfile,
    default_destination_path: str,
    items: list[DownloadBatchItemInput],
) -> CreatedDownloadBatch:
    now = datetime.now(UTC)
    batch = DownloadBatch(
        id=str(uuid4()),
        profile_id=profile.id,
        default_destination_path=default_destination_path,
        total_items=len(items),
        created_at=now,
    )
    jobs = [
        build_queued_download_job(
            profile_id=profile.id,
            source_url=item.source_url,
            destination_path=item.destination_path,
            requested_filename=item.requested_filename,
            created_at=now,
            batch_id=batch.id,
        )
        for item in items
    ]
    try:
        persisted_batch = repository.create_batch_with_jobs_and_events(batch, jobs, now)
    except DownloadJobRepositoryError as exc:
        raise DownloadPersistenceError from exc
    return CreatedDownloadBatch(batch=persisted_batch, jobs=jobs)


def build_queued_download_job(
    profile_id: str,
    source_url: str,
    destination_path: str,
    requested_filename: str | None,
    created_at: datetime,
    batch_id: str | None = None,
) -> DownloadJob:
    return DownloadJob(
        id=str(uuid4()),
        profile_id=profile_id,
        batch_id=batch_id,
        source_url=source_url,
        destination_relative_path=destination_path,
        requested_filename=requested_filename,
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
        created_at=created_at,
        updated_at=created_at,
        started_at=None,
        finished_at=None,
    )


def list_download_jobs(
    repository: DownloadJobWriter,
    limit: int,
    offset: int,
    profile_id: str | None = None,
    status: str | None = None,
    batch_id: str | None = None,
    profile_ids: set[str] | None = None,
) -> tuple[list[DownloadJob], int]:
    try:
        try:
            return repository.list_jobs(
                limit, offset, profile_id, status, batch_id, profile_ids
            )
        except TypeError:
            return repository.list_jobs(limit, offset, profile_id, status, batch_id)
    except DownloadJobRepositoryError as exc:
        raise DownloadPersistenceError from exc


def get_download_job(repository: DownloadJobWriter, job_id: str) -> DownloadJob:
    safe_job_id = validate_job_id(job_id)
    try:
        job = repository.get_job(safe_job_id)
    except DownloadJobRepositoryError as exc:
        raise DownloadPersistenceError from exc
    if job is None:
        raise DownloadJobNotFoundError
    return job


def list_download_job_events(
    repository: DownloadJobWriter,
    job_id: str,
    limit: int,
    offset: int,
) -> tuple[list[DownloadJobEvent], int]:
    safe_job_id = validate_job_id(job_id)
    try:
        job = repository.get_job(safe_job_id)
        if job is None:
            raise DownloadJobNotFoundError
        return repository.list_events(safe_job_id, limit, offset)
    except DownloadJobRepositoryError as exc:
        raise DownloadPersistenceError from exc


def validate_job_id(job_id: str) -> str:
    try:
        parsed_job_id = UUID(job_id, version=4)
    except ValueError as exc:
        raise InvalidDownloadJobIdError from exc
    if str(parsed_job_id) != job_id.lower():
        raise InvalidDownloadJobIdError
    return job_id


def list_download_batches(
    repository: DownloadJobWriter,
    profile_id: str,
    limit: int,
    offset: int,
) -> tuple[list[DownloadBatch], int]:
    try:
        return repository.list_batches(profile_id, limit, offset)
    except DownloadJobRepositoryError as exc:
        raise DownloadPersistenceError from exc


def get_download_batch(repository: DownloadJobWriter, batch_id: str) -> DownloadBatch:
    safe_batch_id = validate_job_id(batch_id)
    try:
        batch = repository.get_batch(safe_batch_id)
    except DownloadJobRepositoryError as exc:
        raise DownloadPersistenceError from exc
    if batch is None:
        raise DownloadJobNotFoundError
    return batch
