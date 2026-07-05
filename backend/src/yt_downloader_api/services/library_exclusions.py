import json
from pathlib import Path
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)


class LibraryExclusionsConfigurationError(Exception):
    """Raised when library exclusions configuration cannot be loaded safely."""


class LibraryExclusionsConfig(BaseModel):
    excluded_names: list[str]

    model_config = ConfigDict(extra="forbid")

    @field_validator("excluded_names")
    @classmethod
    def validate_excluded_names(cls, value: list[str]) -> list[str]:
        normalized_names: list[str] = []
        seen_names: set[str] = set()
        for raw_name in value:
            name = raw_name.strip()
            if not is_valid_excluded_name(name):
                raise ValueError("excluded_names must contain safe base names only")
            casefolded_name = name.casefold()
            if casefolded_name not in seen_names:
                seen_names.add(casefolded_name)
                normalized_names.append(name)
        return sorted(normalized_names, key=str.casefold)

    @model_validator(mode="after")
    def validate_required_list(self) -> Self:
        if self.excluded_names is None:
            raise ValueError("excluded_names is required")
        return self


def load_library_excluded_names(config_path: str) -> frozenset[str]:
    raw_config = read_library_exclusions_config(config_path)
    if raw_config is None:
        return frozenset()
    try:
        config = LibraryExclusionsConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise LibraryExclusionsConfigurationError from exc
    return frozenset(name.casefold() for name in config.excluded_names)


def read_library_exclusions_config(config_path: str) -> Any | None:
    try:
        with Path(config_path).open(encoding="utf-8") as config_file:
            return json.load(config_file)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise LibraryExclusionsConfigurationError from exc


def is_valid_excluded_name(name: str) -> bool:
    return bool(
        name
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
        and name not in {".", ".."}
        and not any(ord(character) < 32 for character in name)
    )
