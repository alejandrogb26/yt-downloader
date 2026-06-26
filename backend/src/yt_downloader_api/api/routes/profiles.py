from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from yt_downloader_api.core.config import get_settings
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
    load_enabled_profiles,
)

router = APIRouter(tags=["profiles"])

PROFILES_UNAVAILABLE_MESSAGE = "Profiles configuration is unavailable."
PROFILE_NOT_FOUND_MESSAGE = "Profile not found."
INVALID_DIRECTORY_PATH_MESSAGE = "Invalid directory path."
DIRECTORY_NOT_FOUND_MESSAGE = "Directory not found."
REQUESTED_PATH_NOT_DIRECTORY_MESSAGE = "Requested path is not a directory."
PROFILE_STORAGE_UNAVAILABLE_MESSAGE = "Profile storage is unavailable."


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
