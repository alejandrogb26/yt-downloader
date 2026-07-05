import re

MAX_REQUESTED_FILENAME_LENGTH = 180
DISALLOWED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".webm",
}


class InvalidRequestedFilenameError(Exception):
    """Raised when a user-provided filename base is unsafe."""


class RequestedFilenameHasExtensionError(InvalidRequestedFilenameError):
    """Raised when the user includes an audio extension."""


def validate_requested_filename(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    if not cleaned:
        raise InvalidRequestedFilenameError
    if len(cleaned) > MAX_REQUESTED_FILENAME_LENGTH:
        raise InvalidRequestedFilenameError
    if cleaned in {".", ".."} or cleaned.startswith("."):
        raise InvalidRequestedFilenameError
    if any(character in cleaned for character in ("/", "\\", "\x00")):
        raise InvalidRequestedFilenameError
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise InvalidRequestedFilenameError
    if has_disallowed_audio_extension(cleaned):
        raise RequestedFilenameHasExtensionError
    return cleaned


def has_disallowed_audio_extension(value: str) -> bool:
    lowered = value.lower()
    return any(lowered.endswith(extension) for extension in DISALLOWED_AUDIO_EXTENSIONS)
