import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from yt_downloader_api.models.profiles import LibraryProfile, ProfilesConfig


class ProfilesConfigurationError(Exception):
    """Raised when the profiles configuration cannot be loaded safely."""


def load_enabled_profiles(config_path: str) -> list[LibraryProfile]:
    config = load_profiles_config(config_path)
    return [profile for profile in config.profiles if profile.enabled]


def load_enabled_profile(config_path: str, profile_id: str) -> LibraryProfile | None:
    for profile in load_enabled_profiles(config_path):
        if profile.id == profile_id:
            return profile
    return None


def load_profiles_config(config_path: str) -> ProfilesConfig:
    raw_config = read_profiles_config(config_path)
    try:
        return ProfilesConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise ProfilesConfigurationError from exc


def read_profiles_config(config_path: str) -> Any:
    try:
        with Path(config_path).open(encoding="utf-8") as config_file:
            return json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfilesConfigurationError from exc
