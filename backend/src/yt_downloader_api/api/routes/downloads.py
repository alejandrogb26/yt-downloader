from collections.abc import Generator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from yt_downloader_api.core.config import get_settings
from yt_downloader_api.db.models import DownloadJob, DownloadJobEvent, DownloadJobStatus
from yt_downloader_api.db.session import DatabaseConfigurationError, get_db_session
from yt_downloader_api.repositories.download_jobs import DownloadJobRepository
from yt_downloader_api.services.downloads import (
    DownloadJobNotFoundError,
    DownloadJobWriter,
    DownloadPersistenceError,
    InvalidDownloadJobIdError,
    create_queued_download_job,
    get_download_job,
    list_download_job_events,
    list_download_jobs,
)
from yt_downloader_api.services.filesystem import (
    DirectoryNotFoundError,
    InvalidDirectoryPathError,
    ProfileStorageUnavailableError,
    RequestedPathNotDirectoryError,
    list_directory_entries,
    validate_relative_directory_path,
)
from yt_downloader_api.services.profiles import (
    ProfilesConfigurationError,
    load_enabled_profile,
)
from yt_downloader_api.services.source_urls import (
    InvalidSourceUrlError,
    validate_source_url,
)

router = APIRouter(tags=["downloads"])

PROFILE_NOT_FOUND_MESSAGE = "Profile not found."
PROFILES_UNAVAILABLE_MESSAGE = "Profiles configuration is unavailable."
INVALID_DIRECTORY_PATH_MESSAGE = "Invalid directory path."
DIRECTORY_NOT_FOUND_MESSAGE = "Directory not found."
REQUESTED_PATH_NOT_DIRECTORY_MESSAGE = "Requested path is not a directory."
PROFILE_STORAGE_UNAVAILABLE_MESSAGE = "Profile storage is unavailable."
INVALID_SOURCE_URL_MESSAGE = "Invalid source URL."
DOWNLOAD_SERVICE_UNAVAILABLE_MESSAGE = "Download service is unavailable."
DOWNLOAD_JOB_NOT_FOUND_MESSAGE = "Download job not found."


class CreateDownloadRequest(BaseModel):
    profile_id: str
    source_url: str
    destination_path: str = ""


class DownloadProfileResponse(BaseModel):
    id: str
    display_name: str


class DownloadJobResponse(BaseModel):
    id: str
    profile: DownloadProfileResponse
    source_url: str
    destination_path: str
    audio_policy: str
    status: str
    progress_percent: int | None
    title: str | None
    output_path: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class DownloadJobListItemResponse(BaseModel):
    id: str
    profile_id: str
    source_url: str
    destination_path: str
    audio_policy: str
    status: str
    progress_percent: int | None
    title: str | None
    output_path: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class DownloadJobDetailResponse(DownloadJobListItemResponse):
    source_format_id: str | None
    source_container: str | None
    source_audio_codec: str | None
    output_container: str | None
    output_audio_codec: str | None
    transcode_applied: bool
    attempt_count: int


class DownloadJobEventResponse(BaseModel):
    created_at: str
    level: str
    message: str
    progress_percent: int | None


class DownloadJobListResponse(BaseModel):
    items: list[DownloadJobListItemResponse]
    total: int
    limit: int
    offset: int


class DownloadJobEventListResponse(BaseModel):
    items: list[DownloadJobEventResponse]
    total: int
    limit: int
    offset: int


def get_download_job_repository() -> Generator[DownloadJobWriter]:
    session_generator = get_db_session()
    try:
        session = next(session_generator)
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DOWNLOAD_SERVICE_UNAVAILABLE_MESSAGE,
        ) from exc

    try:
        yield DownloadJobRepository(session)
    finally:
        session_generator.close()


@router.get("/downloads", response_model=DownloadJobListResponse)
def list_downloads(
    repository: Annotated[DownloadJobWriter, Depends(get_download_job_repository)],
    profile_id: str | None = None,
    status_filter: Annotated[DownloadJobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DownloadJobListResponse:
    try:
        jobs, total = list_download_jobs(
            repository=repository,
            limit=limit,
            offset=offset,
            profile_id=profile_id,
            status=status_filter.value if status_filter else None,
        )
    except DownloadPersistenceError as exc:
        raise download_service_unavailable(exc) from exc

    return DownloadJobListResponse(
        items=[to_download_list_item_response(job) for job in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/downloads/{job_id}", response_model=DownloadJobDetailResponse)
def get_download(
    job_id: str,
    repository: Annotated[DownloadJobWriter, Depends(get_download_job_repository)],
) -> DownloadJobDetailResponse:
    try:
        job = get_download_job(repository, job_id)
    except InvalidDownloadJobIdError as exc:
        raise HTTPException(status_code=422, detail="Invalid download job ID.") from exc
    except DownloadJobNotFoundError as exc:
        raise download_job_not_found(exc) from exc
    except DownloadPersistenceError as exc:
        raise download_service_unavailable(exc) from exc

    return to_download_detail_response(job)


@router.get("/downloads/{job_id}/events", response_model=DownloadJobEventListResponse)
def list_download_events(
    job_id: str,
    repository: Annotated[DownloadJobWriter, Depends(get_download_job_repository)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DownloadJobEventListResponse:
    try:
        events, total = list_download_job_events(repository, job_id, limit, offset)
    except InvalidDownloadJobIdError as exc:
        raise HTTPException(status_code=422, detail="Invalid download job ID.") from exc
    except DownloadJobNotFoundError as exc:
        raise download_job_not_found(exc) from exc
    except DownloadPersistenceError as exc:
        raise download_service_unavailable(exc) from exc

    return DownloadJobEventListResponse(
        items=[to_download_event_response(event) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/downloads", response_model=DownloadJobResponse, status_code=201)
def create_download(
    request: CreateDownloadRequest,
    repository: Annotated[DownloadJobWriter, Depends(get_download_job_repository)],
) -> DownloadJobResponse:
    try:
        source_url = validate_source_url(request.source_url)
    except InvalidSourceUrlError as exc:
        raise HTTPException(status_code=422, detail=INVALID_SOURCE_URL_MESSAGE) from exc

    try:
        destination_path = validate_relative_directory_path(request.destination_path)
    except InvalidDirectoryPathError as exc:
        raise HTTPException(
            status_code=422,
            detail=INVALID_DIRECTORY_PATH_MESSAGE,
        ) from exc

    settings = get_settings()
    try:
        profile = load_enabled_profile(
            settings.profiles_config_path,
            request.profile_id,
        )
    except ProfilesConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILES_UNAVAILABLE_MESSAGE,
        ) from exc

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PROFILE_NOT_FOUND_MESSAGE,
        )

    try:
        list_directory_entries(profile.root_path, destination_path)
    except InvalidDirectoryPathError as exc:
        raise HTTPException(
            status_code=422,
            detail=INVALID_DIRECTORY_PATH_MESSAGE,
        ) from exc
    except DirectoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DIRECTORY_NOT_FOUND_MESSAGE,
        ) from exc
    except RequestedPathNotDirectoryError as exc:
        raise HTTPException(
            status_code=422,
            detail=REQUESTED_PATH_NOT_DIRECTORY_MESSAGE,
        ) from exc
    except ProfileStorageUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILE_STORAGE_UNAVAILABLE_MESSAGE,
        ) from exc

    try:
        job = create_queued_download_job(
            repository=repository,
            profile=profile,
            source_url=source_url,
            destination_path=destination_path,
        )
    except DownloadPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DOWNLOAD_SERVICE_UNAVAILABLE_MESSAGE,
        ) from exc

    return DownloadJobResponse(
        id=job.id,
        profile=DownloadProfileResponse(
            id=job.profile.id,
            display_name=job.profile.display_name,
        ),
        source_url=job.source_url,
        destination_path=job.destination_path,
        audio_policy=job.audio_policy,
        status=job.status,
        progress_percent=job.progress_percent,
        title=job.title,
        output_path=job.output_path,
        created_at=format_utc_datetime(job.created_at),
        started_at=format_optional_utc_datetime(job.started_at),
        finished_at=format_optional_utc_datetime(job.finished_at),
    )


def format_optional_utc_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return format_utc_datetime(value)


def format_utc_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def to_download_list_item_response(job: DownloadJob) -> DownloadJobListItemResponse:
    return DownloadJobListItemResponse(
        id=job.id,
        profile_id=job.profile_id,
        source_url=job.source_url,
        destination_path=job.destination_relative_path,
        audio_policy=job.audio_policy,
        status=job.status,
        progress_percent=job.progress_percent,
        title=job.title,
        output_path=job.output_relative_path,
        created_at=format_utc_datetime(job.created_at),
        started_at=format_optional_utc_datetime(job.started_at),
        finished_at=format_optional_utc_datetime(job.finished_at),
    )


def to_download_detail_response(job: DownloadJob) -> DownloadJobDetailResponse:
    return DownloadJobDetailResponse(
        **to_download_list_item_response(job).model_dump(),
        source_format_id=job.source_format_id,
        source_container=job.source_container,
        source_audio_codec=job.source_audio_codec,
        output_container=job.output_container,
        output_audio_codec=job.output_audio_codec,
        transcode_applied=job.transcode_applied,
        attempt_count=job.attempt_count,
    )


def to_download_event_response(event: DownloadJobEvent) -> DownloadJobEventResponse:
    return DownloadJobEventResponse(
        created_at=format_utc_datetime(event.created_at),
        level=event.level,
        message=event.message,
        progress_percent=event.progress_percent,
    )


def download_job_not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DOWNLOAD_JOB_NOT_FOUND_MESSAGE,
    )


def download_service_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=DOWNLOAD_SERVICE_UNAVAILABLE_MESSAGE,
    )
