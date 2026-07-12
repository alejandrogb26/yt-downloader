from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from yt_downloader_api.api.dependencies import (
    AuthContext,
    get_auth_context,
    require_csrf_token,
)
from yt_downloader_api.core.config import get_settings
from yt_downloader_api.services.db_profiles import (
    ProfilePersistenceError,
    get_authorized_profile,
    list_authorized_profiles,
)
from yt_downloader_api.services.filesystem import (
    CannotMoveDirectoryIntoItselfError,
    DirectoryNotFoundError,
    EntryAlreadyExistsError,
    EntryNotFoundError,
    InvalidDirectoryNameError,
    InvalidDirectoryPathError,
    InvalidEntryPathError,
    ProfileStorageUnavailableError,
    RequestedDirectoryNotAllowedError,
    RequestedEntryNotAllowedError,
    RequestedPathNotDirectoryError,
    create_directory,
    list_directory_entries,
    move_entry,
    rename_entry,
    search_entries,
    trash_entry,
    validate_relative_directory_path,
)
from yt_downloader_api.services.library_exclusions import (
    LibraryExclusionsConfigurationError,
    load_library_excluded_names,
)

router = APIRouter(tags=["profiles"])

PROFILES_UNAVAILABLE_MESSAGE = "Profiles configuration is unavailable."
PROFILE_NOT_FOUND_MESSAGE = "Profile not found."
INVALID_DIRECTORY_PATH_MESSAGE = "Invalid directory path."
INVALID_DIRECTORY_NAME_MESSAGE = "Invalid directory name."
INVALID_ENTRY_PATH_MESSAGE = "Invalid entry path."
INVALID_ENTRY_NAME_MESSAGE = "Invalid entry name."
DIRECTORY_NOT_FOUND_MESSAGE = "Directory not found."
ENTRY_NOT_FOUND_MESSAGE = "Entry not found."
REQUESTED_ENTRY_NOT_ALLOWED_MESSAGE = "Requested entry is not allowed."
REQUESTED_DIRECTORY_NOT_ALLOWED_MESSAGE = "Requested directory is not allowed."
REQUESTED_PATH_NOT_DIRECTORY_MESSAGE = "Requested path is not a directory."
PROFILE_STORAGE_UNAVAILABLE_MESSAGE = "Profile storage is unavailable."
ENTRY_ALREADY_EXISTS_MESSAGE = "An entry with this name already exists."
CANNOT_MOVE_DIRECTORY_INTO_ITSELF_MESSAGE = "Cannot move a directory into itself."
LIBRARY_EXCLUSIONS_UNAVAILABLE_MESSAGE = "Library exclusions configuration is invalid."
INVALID_SEARCH_QUERY_MESSAGE = "Invalid search query."


class PublicProfile(BaseModel):
    id: str
    display_name: str


class ProfilesResponse(BaseModel):
    profiles: list[PublicProfile]


class ProfileEntry(BaseModel):
    name: str
    path: str
    type: str
    size_bytes: int | None


class ProfileEntriesResponse(BaseModel):
    profile: PublicProfile
    path: str
    entries: list[ProfileEntry]


class ProfileSearchResponse(BaseModel):
    profile: PublicProfile
    q: str
    limit: int
    truncated: bool
    results: list[ProfileEntry]


class CreateDirectoryRequest(BaseModel):
    parent_path: str = ""
    name: str


class CreatedDirectoryResponse(BaseModel):
    name: str
    path: str
    type: str


class RenameEntryRequest(BaseModel):
    path: str
    new_name: str


class MoveEntryRequest(BaseModel):
    source_path: str
    target_directory_path: str = ""


class TrashEntryRequest(BaseModel):
    path: str


class TrashEntryResponse(BaseModel):
    status: str
    original_path: str


@router.get("/profiles", response_model=ProfilesResponse)
def list_profiles(
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> ProfilesResponse:
    try:
        profiles = list_authorized_profiles(context.session, context.auth.user)
    except ProfilePersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILES_UNAVAILABLE_MESSAGE,
        ) from exc

    return ProfilesResponse(
        profiles=[
            PublicProfile(id=profile.id, display_name=profile.display_name)
            for profile in profiles
        ]
    )


@router.get("/profiles/{profile_id}/entries", response_model=ProfileEntriesResponse)
def list_profile_entries(
    profile_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    path: str = "",
) -> ProfileEntriesResponse:
    try:
        safe_path = validate_relative_directory_path(path)
    except InvalidDirectoryPathError as exc:
        raise HTTPException(
            status_code=422,
            detail=INVALID_DIRECTORY_PATH_MESSAGE,
        ) from exc

    profile, excluded_names = load_profile_and_exclusions(context, profile_id)

    try:
        entries = list_directory_entries(profile.root_path, safe_path, excluded_names)
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
            detail=REQUESTED_ENTRY_NOT_ALLOWED_MESSAGE,
        ) from exc
    except ProfileStorageUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILE_STORAGE_UNAVAILABLE_MESSAGE,
        ) from exc

    return ProfileEntriesResponse(
        profile=PublicProfile(id=profile.id, display_name=profile.display_name),
        path=safe_path,
        entries=[
            ProfileEntry(
                name=entry.name,
                path=entry.path,
                type=entry.type,
                size_bytes=entry.size_bytes,
            )
            for entry in entries
        ],
    )


@router.get("/profiles/{profile_id}/search", response_model=ProfileSearchResponse)
def search_profile_entries(
    profile_id: str,
    q: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    limit: int = 50,
) -> ProfileSearchResponse:
    profile, excluded_names = load_profile_and_exclusions(context, profile_id)

    try:
        results, truncated = search_entries(profile.root_path, q, limit, excluded_names)
    except InvalidEntryPathError as exc:
        raise HTTPException(
            status_code=422, detail=INVALID_SEARCH_QUERY_MESSAGE
        ) from exc
    except ProfileStorageUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILE_STORAGE_UNAVAILABLE_MESSAGE,
        ) from exc

    return ProfileSearchResponse(
        profile=PublicProfile(id=profile.id, display_name=profile.display_name),
        q=q.strip(),
        limit=limit,
        truncated=truncated,
        results=[
            ProfileEntry(
                name=entry.name,
                path=entry.path,
                type=entry.type,
                size_bytes=entry.size_bytes,
            )
            for entry in results
        ],
    )


@router.post(
    "/profiles/{profile_id}/directories",
    response_model=CreatedDirectoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_profile_directory(
    profile_id: str,
    request: CreateDirectoryRequest,
    context: Annotated[AuthContext, Depends(require_csrf_token)],
) -> CreatedDirectoryResponse:
    profile, excluded_names = load_profile_and_exclusions(context, profile_id, True)

    try:
        created_directory = create_directory(
            profile.root_path,
            request.parent_path,
            request.name,
            excluded_names,
        )
    except InvalidDirectoryPathError as exc:
        raise HTTPException(
            status_code=422,
            detail=INVALID_DIRECTORY_PATH_MESSAGE,
        ) from exc
    except InvalidDirectoryNameError as exc:
        raise HTTPException(
            status_code=422,
            detail=INVALID_DIRECTORY_NAME_MESSAGE,
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
            detail=REQUESTED_ENTRY_NOT_ALLOWED_MESSAGE,
        ) from exc
    except EntryAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ENTRY_ALREADY_EXISTS_MESSAGE,
        ) from exc
    except ProfileStorageUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILE_STORAGE_UNAVAILABLE_MESSAGE,
        ) from exc

    return CreatedDirectoryResponse(
        name=created_directory.name,
        path=created_directory.path,
        type=created_directory.type,
    )


@router.patch("/profiles/{profile_id}/entries/rename", response_model=ProfileEntry)
def rename_profile_entry(
    profile_id: str,
    request: RenameEntryRequest,
    context: Annotated[AuthContext, Depends(require_csrf_token)],
) -> ProfileEntry:
    profile, excluded_names = load_profile_and_exclusions(context, profile_id, True)

    try:
        renamed_entry = rename_entry(
            profile.root_path,
            request.path,
            request.new_name,
            excluded_names,
        )
    except InvalidEntryPathError as exc:
        raise HTTPException(status_code=422, detail=INVALID_ENTRY_PATH_MESSAGE) from exc
    except InvalidDirectoryNameError as exc:
        raise HTTPException(status_code=422, detail=INVALID_ENTRY_NAME_MESSAGE) from exc
    except EntryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ENTRY_NOT_FOUND_MESSAGE,
        ) from exc
    except RequestedEntryNotAllowedError as exc:
        raise HTTPException(
            status_code=422,
            detail=REQUESTED_ENTRY_NOT_ALLOWED_MESSAGE,
        ) from exc
    except EntryAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ENTRY_ALREADY_EXISTS_MESSAGE,
        ) from exc
    except ProfileStorageUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILE_STORAGE_UNAVAILABLE_MESSAGE,
        ) from exc

    return ProfileEntry(
        name=renamed_entry.name,
        path=renamed_entry.path,
        type=renamed_entry.type,
        size_bytes=renamed_entry.size_bytes,
    )


@router.post("/profiles/{profile_id}/entries/move", response_model=ProfileEntry)
def move_profile_entry(
    profile_id: str,
    request: MoveEntryRequest,
    context: Annotated[AuthContext, Depends(require_csrf_token)],
) -> ProfileEntry:
    profile, excluded_names = load_profile_and_exclusions(context, profile_id, True)

    try:
        moved_entry = move_entry(
            profile.root_path,
            request.source_path,
            request.target_directory_path,
            excluded_names,
        )
    except InvalidEntryPathError as exc:
        raise HTTPException(status_code=422, detail=INVALID_ENTRY_PATH_MESSAGE) from exc
    except InvalidDirectoryPathError as exc:
        raise HTTPException(
            status_code=422,
            detail=INVALID_DIRECTORY_PATH_MESSAGE,
        ) from exc
    except EntryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ENTRY_NOT_FOUND_MESSAGE,
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
            detail=REQUESTED_ENTRY_NOT_ALLOWED_MESSAGE,
        ) from exc
    except RequestedDirectoryNotAllowedError as exc:
        raise HTTPException(
            status_code=422,
            detail=REQUESTED_DIRECTORY_NOT_ALLOWED_MESSAGE,
        ) from exc
    except CannotMoveDirectoryIntoItselfError as exc:
        raise HTTPException(
            status_code=422,
            detail=CANNOT_MOVE_DIRECTORY_INTO_ITSELF_MESSAGE,
        ) from exc
    except EntryAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ENTRY_ALREADY_EXISTS_MESSAGE,
        ) from exc
    except ProfileStorageUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILE_STORAGE_UNAVAILABLE_MESSAGE,
        ) from exc

    return ProfileEntry(
        name=moved_entry.name,
        path=moved_entry.path,
        type=moved_entry.type,
        size_bytes=moved_entry.size_bytes,
    )


@router.delete("/profiles/{profile_id}/entries", response_model=TrashEntryResponse)
def trash_profile_entry(
    profile_id: str,
    request: TrashEntryRequest,
    context: Annotated[AuthContext, Depends(require_csrf_token)],
) -> TrashEntryResponse:
    profile, excluded_names = load_profile_and_exclusions(context, profile_id, True)

    try:
        trashed_entry = trash_entry(profile.root_path, request.path, excluded_names)
    except InvalidEntryPathError as exc:
        raise HTTPException(status_code=422, detail=INVALID_ENTRY_PATH_MESSAGE) from exc
    except EntryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ENTRY_NOT_FOUND_MESSAGE,
        ) from exc
    except RequestedEntryNotAllowedError as exc:
        raise HTTPException(
            status_code=422,
            detail=REQUESTED_ENTRY_NOT_ALLOWED_MESSAGE,
        ) from exc
    except ProfileStorageUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PROFILE_STORAGE_UNAVAILABLE_MESSAGE,
        ) from exc

    return TrashEntryResponse(
        status=trashed_entry.status,
        original_path=trashed_entry.original_path,
    )


def load_profile_and_exclusions(
    context: AuthContext,
    profile_id: str,
    require_write: bool = False,
):
    settings = get_settings()
    try:
        profile = get_authorized_profile(
            context.session,
            context.auth.user,
            profile_id,
            require_write=require_write,
        )
        excluded_names = load_library_excluded_names(
            settings.library_exclusions_config_path
        )
    except ProfilePersistenceError as exc:
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
