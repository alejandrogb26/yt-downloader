from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from yt_downloader_api.core.config import get_settings
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
    validate_relative_directory_path,
)
from yt_downloader_api.services.profiles import (
    ProfilesConfigurationError,
    load_enabled_profile,
    load_enabled_profiles,
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


@router.get("/profiles", response_model=ProfilesResponse)
def list_profiles() -> ProfilesResponse:
    settings = get_settings()
    try:
        profiles = load_enabled_profiles(settings.profiles_config_path)
    except ProfilesConfigurationError as exc:
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
def list_profile_entries(profile_id: str, path: str = "") -> ProfileEntriesResponse:
    settings = get_settings()
    try:
        safe_path = validate_relative_directory_path(path)
    except InvalidDirectoryPathError as exc:
        raise HTTPException(
            status_code=422,
            detail=INVALID_DIRECTORY_PATH_MESSAGE,
        ) from exc

    try:
        profile = load_enabled_profile(settings.profiles_config_path, profile_id)
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
        entries = list_directory_entries(profile.root_path, safe_path)
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


@router.post(
    "/profiles/{profile_id}/directories",
    response_model=CreatedDirectoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_profile_directory(
    profile_id: str,
    request: CreateDirectoryRequest,
) -> CreatedDirectoryResponse:
    settings = get_settings()
    try:
        profile = load_enabled_profile(settings.profiles_config_path, profile_id)
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
        created_directory = create_directory(
            profile.root_path,
            request.parent_path,
            request.name,
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
) -> ProfileEntry:
    settings = get_settings()
    try:
        profile = load_enabled_profile(settings.profiles_config_path, profile_id)
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
        renamed_entry = rename_entry(
            profile.root_path,
            request.path,
            request.new_name,
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
) -> ProfileEntry:
    settings = get_settings()
    try:
        profile = load_enabled_profile(settings.profiles_config_path, profile_id)
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
        moved_entry = move_entry(
            profile.root_path,
            request.source_path,
            request.target_directory_path,
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
