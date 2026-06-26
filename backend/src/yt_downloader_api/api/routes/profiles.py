from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from yt_downloader_api.core.config import get_settings
from yt_downloader_api.services.profiles import (
    ProfilesConfigurationError,
    load_enabled_profiles,
)

router = APIRouter(tags=["profiles"])

PROFILES_UNAVAILABLE_MESSAGE = "Profiles configuration is unavailable."


class PublicProfile(BaseModel):
    id: str
    display_name: str


class ProfilesResponse(BaseModel):
    profiles: list[PublicProfile]


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
