from collections.abc import Generator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from yt_downloader_api.core.config import get_settings
from yt_downloader_api.db.session import DatabaseConfigurationError, get_db_session
from yt_downloader_api.repositories.download_jobs import DownloadJobRepository
from yt_downloader_api.services.downloads import (
    DownloadJobWriter,
    DownloadPersistenceError,
    create_queued_download_job,
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
