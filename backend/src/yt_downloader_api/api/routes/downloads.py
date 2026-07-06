from collections.abc import Generator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from yt_downloader_api.core.config import get_settings
from yt_downloader_api.db.models import (
    DownloadBatch,
    DownloadJob,
    DownloadJobEvent,
    DownloadJobStatus,
)
from yt_downloader_api.db.session import DatabaseConfigurationError, get_db_session
from yt_downloader_api.repositories.download_jobs import DownloadJobRepository
from yt_downloader_api.services.downloads import (
    DownloadBatchItemInput,
    DownloadJobNotFoundError,
    DownloadJobWriter,
    DownloadPersistenceError,
    InvalidDownloadJobIdError,
    create_queued_download_batch,
    create_queued_download_job,
    get_download_batch,
    get_download_job,
    list_download_batches,
    list_download_job_events,
    list_download_jobs,
)
from yt_downloader_api.services.filenames import (
    InvalidRequestedFilenameError,
    RequestedFilenameHasExtensionError,
    validate_requested_filename,
)
from yt_downloader_api.services.filesystem import (
    DirectoryNotFoundError,
    InvalidDirectoryPathError,
    ProfileStorageUnavailableError,
    RequestedEntryNotAllowedError,
    RequestedPathNotDirectoryError,
    list_directory_entries,
    validate_relative_directory_path,
)
from yt_downloader_api.services.library_exclusions import (
    LibraryExclusionsConfigurationError,
    load_library_excluded_names,
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
INVALID_REQUESTED_FILENAME_MESSAGE = "Invalid requested filename."
REQUESTED_FILENAME_EXTENSION_MESSAGE = (
    "No incluyas la extensión del archivo; el sistema la determina automáticamente."
)
DOWNLOAD_SERVICE_UNAVAILABLE_MESSAGE = "Download service is unavailable."
DOWNLOAD_JOB_NOT_FOUND_MESSAGE = "Download job not found."
DOWNLOAD_BATCH_NOT_FOUND_MESSAGE = "Download batch not found."
LIBRARY_EXCLUSIONS_UNAVAILABLE_MESSAGE = "Library exclusions configuration is invalid."
BATCH_INVALID_MESSAGE = "El lote contiene errores de validación."


class CreateDownloadRequest(BaseModel):
    profile_id: str
    source_url: str
    destination_path: str = ""
    requested_filename: str | None = None


class BatchItemRequest(BaseModel):
    url: str
    destination_path: str | None = None
    requested_filename: str | None = None

    model_config = ConfigDict(extra="forbid")


class BatchRequest(BaseModel):
    default_destination_path: str
    items: list[BatchItemRequest] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid")


class DownloadProfileResponse(BaseModel):
    id: str
    display_name: str


class DownloadJobResponse(BaseModel):
    id: str
    profile: DownloadProfileResponse
    source_url: str
    destination_path: str
    requested_filename: str | None
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
    batch_id: str | None
    profile_id: str
    source_url: str
    destination_path: str
    requested_filename: str | None
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


class BatchPreviewItemResponse(BaseModel):
    index: int
    source_url: str | None
    requested_filename: str | None
    destination_path: str | None
    errors: list[str]


class BatchPreviewResponse(BaseModel):
    valid: bool
    default_destination_path: str | None
    total_items: int
    items: list[BatchPreviewItemResponse]
    errors: list[str]


class DownloadBatchSummaryResponse(BaseModel):
    id: str
    profile_id: str
    default_destination_path: str
    total_items: int
    queued_count: int
    running_count: int
    completed_count: int
    failed_count: int
    cancelled_count: int
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None


class DownloadBatchListResponse(BaseModel):
    items: list[DownloadBatchSummaryResponse]
    total: int
    limit: int
    offset: int


class CreatedDownloadBatchResponse(BaseModel):
    batch: DownloadBatchSummaryResponse
    jobs: list[DownloadJobListItemResponse]


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
    batch_id: str | None = None,
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
            batch_id=batch_id,
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

    try:
        requested_filename = validate_requested_filename(request.requested_filename)
    except RequestedFilenameHasExtensionError as exc:
        raise HTTPException(
            status_code=422,
            detail=REQUESTED_FILENAME_EXTENSION_MESSAGE,
        ) from exc
    except InvalidRequestedFilenameError as exc:
        raise HTTPException(
            status_code=422,
            detail=INVALID_REQUESTED_FILENAME_MESSAGE,
        ) from exc

    settings = get_settings()
    try:
        profile = load_enabled_profile(
            settings.profiles_config_path,
            request.profile_id,
        )
        excluded_names = load_library_excluded_names(
            settings.library_exclusions_config_path
        )
    except ProfilesConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILES_UNAVAILABLE_MESSAGE,
        ) from exc
    except LibraryExclusionsConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=LIBRARY_EXCLUSIONS_UNAVAILABLE_MESSAGE,
        ) from exc

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PROFILE_NOT_FOUND_MESSAGE,
        )

    try:
        list_directory_entries(profile.root_path, destination_path, excluded_names)
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
    except RequestedEntryNotAllowedError as exc:
        raise HTTPException(
            status_code=422,
            detail="Requested entry is not allowed.",
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
            requested_filename=requested_filename,
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
        requested_filename=job.requested_filename,
        audio_policy=job.audio_policy,
        status=job.status,
        progress_percent=job.progress_percent,
        title=job.title,
        output_path=job.output_path,
        created_at=format_utc_datetime(job.created_at),
        started_at=format_optional_utc_datetime(job.started_at),
        finished_at=format_optional_utc_datetime(job.finished_at),
    )


@router.post(
    "/profiles/{profile_id}/download-batches/preview",
    response_model=BatchPreviewResponse,
)
def preview_download_batch(
    profile_id: str, request: BatchRequest
) -> BatchPreviewResponse:
    profile, excluded_names = load_download_profile_and_exclusions(profile_id)
    return validate_batch_request(profile.root_path, request, excluded_names)


@router.post(
    "/profiles/{profile_id}/download-batches",
    response_model=CreatedDownloadBatchResponse,
    status_code=201,
)
def create_download_batch(
    profile_id: str,
    request: BatchRequest,
    repository: Annotated[DownloadJobWriter, Depends(get_download_job_repository)],
) -> CreatedDownloadBatchResponse:
    profile, excluded_names = load_download_profile_and_exclusions(profile_id)
    preview = validate_batch_request(profile.root_path, request, excluded_names)
    if not preview.valid:
        raise HTTPException(status_code=422, detail=BATCH_INVALID_MESSAGE)

    batch_items = [
        DownloadBatchItemInput(
            source_url=item.source_url or "",
            destination_path=item.destination_path or "",
            requested_filename=item.requested_filename,
        )
        for item in preview.items
    ]
    try:
        created = create_queued_download_batch(
            repository,
            profile,
            preview.default_destination_path or "",
            batch_items,
        )
    except DownloadPersistenceError as exc:
        raise download_service_unavailable(exc) from exc

    batch = created.batch
    batch.jobs = created.jobs
    return CreatedDownloadBatchResponse(
        batch=to_batch_summary_response(batch),
        jobs=[to_download_list_item_response(job) for job in created.jobs],
    )


@router.get(
    "/profiles/{profile_id}/download-batches",
    response_model=DownloadBatchListResponse,
)
def list_profile_download_batches(
    profile_id: str,
    repository: Annotated[DownloadJobWriter, Depends(get_download_job_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DownloadBatchListResponse:
    load_download_profile_and_exclusions(profile_id)
    try:
        batches, total = list_download_batches(repository, profile_id, limit, offset)
    except DownloadPersistenceError as exc:
        raise download_service_unavailable(exc) from exc
    return DownloadBatchListResponse(
        items=[to_batch_summary_response(batch) for batch in batches],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/download-batches/{batch_id}", response_model=DownloadBatchSummaryResponse)
def get_download_batch_detail(
    batch_id: str,
    repository: Annotated[DownloadJobWriter, Depends(get_download_job_repository)],
) -> DownloadBatchSummaryResponse:
    try:
        batch = get_download_batch(repository, batch_id)
    except InvalidDownloadJobIdError as exc:
        raise HTTPException(
            status_code=422, detail="Invalid download batch ID."
        ) from exc
    except DownloadJobNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DOWNLOAD_BATCH_NOT_FOUND_MESSAGE,
        ) from exc
    except DownloadPersistenceError as exc:
        raise download_service_unavailable(exc) from exc
    return to_batch_summary_response(batch)


def format_optional_utc_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return format_utc_datetime(value)


def format_utc_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def to_download_list_item_response(job: DownloadJob) -> DownloadJobListItemResponse:
    return DownloadJobListItemResponse(
        id=job.id,
        batch_id=job.batch_id,
        profile_id=job.profile_id,
        source_url=job.source_url,
        destination_path=job.destination_relative_path,
        requested_filename=job.requested_filename,
        audio_policy=job.audio_policy,
        status=job.status,
        progress_percent=job.progress_percent,
        title=job.title,
        output_path=job.output_relative_path,
        created_at=format_utc_datetime(job.created_at),
        started_at=format_optional_utc_datetime(job.started_at),
        finished_at=format_optional_utc_datetime(job.finished_at),
    )


def load_download_profile_and_exclusions(profile_id: str):
    settings = get_settings()
    try:
        profile = load_enabled_profile(settings.profiles_config_path, profile_id)
        excluded_names = load_library_excluded_names(
            settings.library_exclusions_config_path
        )
    except ProfilesConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILES_UNAVAILABLE_MESSAGE,
        ) from exc
    except LibraryExclusionsConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=LIBRARY_EXCLUSIONS_UNAVAILABLE_MESSAGE,
        ) from exc
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PROFILE_NOT_FOUND_MESSAGE,
        )
    return profile, excluded_names


def validate_batch_request(
    root_path: str,
    request: BatchRequest,
    excluded_names: frozenset[str],
) -> BatchPreviewResponse:
    errors: list[str] = []
    try:
        default_destination_path = validate_relative_directory_path(
            request.default_destination_path
        )
        ensure_download_destination(root_path, default_destination_path, excluded_names)
    except Exception:
        default_destination_path = None
        errors.append("La ruta por defecto no es válida o no está disponible.")

    items: list[BatchPreviewItemResponse] = []
    seen_urls: dict[str, int] = {}
    for index, item in enumerate(request.items):
        item_errors: list[str] = []
        source_url: str | None = None
        destination_path: str | None = None
        requested_filename: str | None = None
        try:
            source_url = validate_source_url(item.url)
        except InvalidSourceUrlError:
            item_errors.append("La URL de YouTube no es válida.")

        if source_url is not None:
            if source_url in seen_urls:
                item_errors.append(
                    f"URL duplicada con el elemento {seen_urls[source_url] + 1}."
                )
            else:
                seen_urls[source_url] = index

        raw_destination = (
            item.destination_path
            if item.destination_path is not None
            else request.default_destination_path
        )
        try:
            destination_path = validate_relative_directory_path(raw_destination)
            ensure_download_destination(root_path, destination_path, excluded_names)
        except Exception:
            item_errors.append("La ruta de destino no es válida o no está disponible.")

        try:
            requested_filename = validate_requested_filename(item.requested_filename)
        except RequestedFilenameHasExtensionError:
            item_errors.append(REQUESTED_FILENAME_EXTENSION_MESSAGE)
        except InvalidRequestedFilenameError:
            item_errors.append("El nombre solicitado no es válido.")

        items.append(
            BatchPreviewItemResponse(
                index=index,
                source_url=source_url,
                requested_filename=requested_filename,
                destination_path=destination_path,
                errors=item_errors,
            )
        )

    return BatchPreviewResponse(
        valid=not errors and all(not item.errors for item in items),
        default_destination_path=default_destination_path,
        total_items=len(request.items),
        items=items,
        errors=errors,
    )


def ensure_download_destination(
    root_path: str,
    destination_path: str,
    excluded_names: frozenset[str],
) -> None:
    list_directory_entries(root_path, destination_path, excluded_names)


def to_batch_summary_response(batch: DownloadBatch) -> DownloadBatchSummaryResponse:
    jobs = list(batch.jobs)
    counts = {status.value: 0 for status in DownloadJobStatus}
    for job in jobs:
        counts[job.status] = counts.get(job.status, 0) + 1
    terminal_count = (
        counts[DownloadJobStatus.COMPLETED.value]
        + counts[DownloadJobStatus.FAILED.value]
        + counts[DownloadJobStatus.CANCELLED.value]
    )
    started_values = [job.started_at for job in jobs if job.started_at is not None]
    finished_values = [job.finished_at for job in jobs if job.finished_at is not None]
    return DownloadBatchSummaryResponse(
        id=batch.id,
        profile_id=batch.profile_id,
        default_destination_path=batch.default_destination_path,
        total_items=batch.total_items,
        queued_count=counts[DownloadJobStatus.QUEUED.value],
        running_count=counts[DownloadJobStatus.RUNNING.value],
        completed_count=counts[DownloadJobStatus.COMPLETED.value],
        failed_count=counts[DownloadJobStatus.FAILED.value],
        cancelled_count=counts[DownloadJobStatus.CANCELLED.value],
        status=calculate_batch_status(counts, batch.total_items),
        created_at=format_utc_datetime(batch.created_at),
        started_at=format_optional_utc_datetime(
            min(started_values) if started_values else None
        ),
        finished_at=format_optional_utc_datetime(
            max(finished_values)
            if terminal_count == batch.total_items and finished_values
            else None
        ),
    )


def calculate_batch_status(counts: dict[str, int], total_items: int) -> str:
    queued = counts.get(DownloadJobStatus.QUEUED.value, 0)
    running = counts.get(DownloadJobStatus.RUNNING.value, 0)
    completed = counts.get(DownloadJobStatus.COMPLETED.value, 0)
    failed = counts.get(DownloadJobStatus.FAILED.value, 0)
    cancelled = counts.get(DownloadJobStatus.CANCELLED.value, 0)
    if queued == total_items:
        return "queued"
    if running > 0:
        return "running"
    if completed == total_items:
        return "completed"
    if cancelled == total_items:
        return "cancelled"
    if completed > 0 and completed + failed + cancelled == total_items:
        return "completed_with_errors"
    if failed + cancelled == total_items:
        return "failed"
    return "running"


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
