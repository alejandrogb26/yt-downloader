from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)


class LibraryProfile(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    display_name: str
    root_path: str
    enabled: StrictBool

    model_config = ConfigDict(extra="forbid")

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be empty")
        return value

    @field_validator("root_path")
    @classmethod
    def validate_root_path(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("root_path must be absolute")
        return value


class ProfilesConfig(BaseModel):
    profiles: list[LibraryProfile]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_unique_profile_ids(self) -> Self:
        profile_ids = [profile.id for profile in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("profile IDs must be unique")
        return self
