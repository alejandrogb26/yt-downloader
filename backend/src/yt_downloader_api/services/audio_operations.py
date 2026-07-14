import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex

from yt_downloader_api.services.filesystem import (
    EntryAlreadyExistsError,
    InvalidDirectoryNameError,
    ProfileStorageUnavailableError,
    RequestedEntryNotAllowedError,
    ensure_name_is_not_excluded,
    ensure_path_has_no_excluded_components,
    ensure_writable_root,
    get_parent_relative_path,
    join_relative_path,
    resolve_entry,
    validate_directory_name,
    validate_relative_entry_path,
)

SUPPORTED_AUDIO_EXTENSIONS = frozenset({".m4a"})
ALLOWED_METADATA_KEYS = frozenset(
    {"title", "artist", "album", "album_artist", "genre", "date", "track"}
)
MAX_METADATA_VALUE_LENGTH = 200
TIME_PATTERN = re.compile(
    r"^(?:(?P<hours>\d{1,2}):)?(?:(?P<minutes>\d{1,2}):)?(?P<seconds>\d{1,2}(?:\.\d{1,3})?)$"
)
DURATION_TOLERANCE_SECONDS = 0.5
logger = logging.getLogger(__name__)


class InvalidAudioPathError(Exception):
    """Raised when the requested audio path is invalid or unsupported."""


class InvalidAudioTimeError(Exception):
    """Raised when trim times are invalid."""


class InvalidAudioOutputNameError(Exception):
    """Raised when an output base filename is invalid."""


class InvalidAudioMetadataError(Exception):
    """Raised when metadata fields are invalid."""


class AudioToolUnavailableError(Exception):
    """Raised when ffmpeg or ffprobe cannot be executed."""


class AudioOperationFailedError(Exception):
    """Raised when ffmpeg fails or produces an invalid result."""

    def __init__(self, returncode: int | None = None, stderr: str = "") -> None:
        super().__init__()
        self.returncode = returncode
        self.stderr = stderr


@dataclass(frozen=True)
class AudioOperationResult:
    path: str
    name: str
    operation: str


def trim_audio_file(
    root_path: str,
    source_path: str,
    start: str,
    end: str,
    output_filename: str | None,
    excluded_names: frozenset[str],
    ffmpeg_path: str,
    ffprobe_path: str,
) -> AudioOperationResult:
    root = Path(root_path)
    source = resolve_audio_file(root, source_path, excluded_names)
    start_seconds = parse_audio_time(start)
    end_seconds = parse_audio_time(end)
    if end_seconds <= start_seconds:
        raise InvalidAudioTimeError

    duration = probe_duration(source, ffprobe_path)
    if duration is not None and end_seconds > duration + DURATION_TOLERANCE_SECONDS:
        raise InvalidAudioTimeError

    parent_relative_path = get_parent_relative_path(
        validate_relative_entry_path(source_path)
    )
    output_base_name = validate_output_base_name(output_filename, source.stem)
    output_name = f"{output_base_name}{source.suffix}"
    ensure_name_is_not_excluded(output_name, excluded_names)
    target = source.parent / output_name
    ensure_target_does_not_exist(target)
    temporary = build_temporary_path(source.parent, output_name)

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-ss",
        start,
        "-to",
        end,
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "copy",
        str(temporary),
    ]
    run_ffmpeg(command)
    publish_temporary_file(temporary, target)
    return AudioOperationResult(
        path=join_relative_path(parent_relative_path, output_name),
        name=output_name,
        operation="trim",
    )


def update_audio_metadata(
    root_path: str,
    source_path: str,
    metadata: dict[str, str | None],
    excluded_names: frozenset[str],
    ffmpeg_path: str,
) -> AudioOperationResult:
    root = Path(root_path)
    source = resolve_audio_file(root, source_path, excluded_names)
    safe_metadata = validate_metadata(metadata)
    temporary = build_temporary_path(source.parent, source.name)

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0",
        "-c",
        "copy",
    ]
    for key, value in safe_metadata.items():
        command.extend(["-metadata", f"{key}={value or ''}"])
    command.append(str(temporary))

    run_ffmpeg(command)
    publish_temporary_file(temporary, source)
    return AudioOperationResult(
        path=validate_relative_entry_path(source_path),
        name=source.name,
        operation="metadata",
    )


def read_audio_metadata(
    root_path: str,
    source_path: str,
    excluded_names: frozenset[str],
    ffprobe_path: str,
) -> dict[str, str]:
    source = resolve_audio_file(Path(root_path), source_path, excluded_names)
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format_tags",
        "-of",
        "json",
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "ffprobe could not read audio duration",
            extra={"error": exc.__class__.__name__},
        )
        return None
    if completed.returncode != 0:
        raise AudioOperationFailedError
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AudioOperationFailedError from exc
    tags = payload.get("format", {}).get("tags", {})
    if not isinstance(tags, dict):
        return {}
    return {
        key: str(value)
        for key, value in tags.items()
        if key in ALLOWED_METADATA_KEYS and isinstance(value, str)
    }


def resolve_audio_file(
    root: Path,
    relative_path: str,
    excluded_names: frozenset[str],
) -> Path:
    safe_path = validate_relative_entry_path(relative_path)
    if any(part.startswith(".") for part in safe_path.split("/")):
        raise RequestedEntryNotAllowedError
    ensure_path_has_no_excluded_components(safe_path, excluded_names)
    ensure_writable_root(root)
    source = resolve_entry(root, safe_path)
    if (
        not source.is_file()
        or source.suffix.casefold() not in SUPPORTED_AUDIO_EXTENSIONS
    ):
        raise InvalidAudioPathError
    return source


def parse_audio_time(value: str) -> float:
    if not isinstance(value, str):
        raise InvalidAudioTimeError
    match = TIME_PATTERN.fullmatch(value.strip())
    if match is None:
        raise InvalidAudioTimeError
    parts = value.strip().split(":")
    try:
        if len(parts) == 1:
            total = float(parts[0])
        elif len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            if seconds >= 60:
                raise InvalidAudioTimeError
            total = minutes * 60 + seconds
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            if minutes >= 60 or seconds >= 60:
                raise InvalidAudioTimeError
            total = hours * 3600 + minutes * 60 + seconds
        else:
            raise InvalidAudioTimeError
    except ValueError as exc:
        raise InvalidAudioTimeError from exc
    if total < 0:
        raise InvalidAudioTimeError
    return total


def validate_output_base_name(value: str | None, source_stem: str) -> str:
    raw_name = value.strip() if value is not None else f"{source_stem} - recorte"
    if Path(raw_name).suffix:
        raise InvalidAudioOutputNameError
    try:
        return validate_directory_name(raw_name)
    except InvalidDirectoryNameError as exc:
        raise InvalidAudioOutputNameError from exc


def validate_metadata(metadata: dict[str, str | None]) -> dict[str, str | None]:
    if not metadata:
        raise InvalidAudioMetadataError
    for key, value in metadata.items():
        if key not in ALLOWED_METADATA_KEYS:
            raise InvalidAudioMetadataError
        if value is not None and (
            not isinstance(value, str) or len(value) > MAX_METADATA_VALUE_LENGTH
        ):
            raise InvalidAudioMetadataError
    return metadata


def probe_duration(source: Path, ffprobe_path: str) -> float | None:
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise AudioToolUnavailableError from exc
    if completed.returncode != 0:
        logger.warning(
            "ffprobe could not read audio duration",
            extra={
                "returncode": completed.returncode,
                "stderr_summary": summarize_stderr(completed.stderr),
            },
        )
        return None
    try:
        return float(completed.stdout.strip())
    except ValueError:
        logger.warning("ffprobe returned invalid audio duration")
        return None


def run_ffmpeg(command: list[str]) -> None:
    ensure_copy_codec(command)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        cleanup_command_output(command)
        raise AudioToolUnavailableError from exc
    if completed.returncode != 0:
        cleanup_command_output(command)
        raise AudioOperationFailedError(completed.returncode, completed.stderr)


def ensure_copy_codec(command: list[str]) -> None:
    for option in ("-c", "-c:a"):
        if option in command and command[command.index(option) + 1] == "copy":
            return
    raise AudioOperationFailedError


def ensure_target_does_not_exist(target: Path) -> None:
    try:
        target.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ProfileStorageUnavailableError from exc
    raise EntryAlreadyExistsError


def build_temporary_path(directory: Path, final_name: str) -> Path:
    final_path = Path(final_name)
    temporary_name = (
        f".yt-downloader-{token_hex(8)}-{final_path.stem}.tmp{final_path.suffix}"
    )
    return directory / temporary_name


def publish_temporary_file(temporary: Path, target: Path) -> None:
    try:
        if temporary.stat(follow_symlinks=False).st_size <= 0:
            raise AudioOperationFailedError
        os.replace(temporary, target)
    except AudioOperationFailedError:
        cleanup_path(temporary)
        raise
    except OSError as exc:
        cleanup_path(temporary)
        raise ProfileStorageUnavailableError from exc


def cleanup_command_output(command: list[str]) -> None:
    if command:
        cleanup_path(Path(command[-1]))


def cleanup_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def summarize_stderr(stderr: str, limit: int = 500) -> str:
    summary = re.sub(r"/[^\s'\"]+", "[path]", stderr).strip()
    if len(summary) > limit:
        return f"{summary[:limit]}..."
    return summary
