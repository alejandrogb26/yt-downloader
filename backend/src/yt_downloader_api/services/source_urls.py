from urllib.parse import parse_qs, urlsplit

ALLOWED_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}
YOUTUBE_WATCH_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}
YOUTU_BE_HOSTS = {"youtu.be", "www.youtu.be"}
MAX_SOURCE_URL_LENGTH = 2048
CANONICAL_YOUTUBE_VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"


class InvalidSourceUrlError(Exception):
    """Raised when a source URL is not an accepted YouTube video URL."""


def validate_source_url(source_url: str) -> str:
    if "\x00" in source_url or len(source_url) > MAX_SOURCE_URL_LENGTH:
        raise InvalidSourceUrlError

    try:
        parsed_url = urlsplit(source_url)
    except ValueError as exc:
        raise InvalidSourceUrlError from exc

    host = parsed_url.hostname
    try:
        port = parsed_url.port
    except ValueError as exc:
        raise InvalidSourceUrlError from exc
    if (
        parsed_url.scheme != "https"
        or not host
        or host not in ALLOWED_YOUTUBE_HOSTS
        or parsed_url.username is not None
        or parsed_url.password is not None
        or port not in {None, 443}
    ):
        raise InvalidSourceUrlError

    query = parse_qs(parsed_url.query, keep_blank_values=True)
    if host in YOUTUBE_WATCH_HOSTS:
        video_id = extract_youtube_video_id(parsed_url.path, query)
    elif host in YOUTU_BE_HOSTS:
        video_id = extract_youtu_be_video_id(parsed_url.path)
    else:
        raise InvalidSourceUrlError

    return CANONICAL_YOUTUBE_VIDEO_URL.format(video_id=video_id)


def extract_youtube_video_id(path: str, query: dict[str, list[str]]) -> str:
    if path == "/watch":
        return validate_video_id(query.get("v", [""])[0])

    path_parts = [part for part in path.split("/") if part]
    if len(path_parts) == 2 and path_parts[0] in {"shorts", "live", "embed"}:
        return validate_video_id(path_parts[1])

    raise InvalidSourceUrlError


def extract_youtu_be_video_id(path: str) -> str:
    path_parts = [part for part in path.split("/") if part]
    if len(path_parts) == 1:
        return validate_video_id(path_parts[0])
    raise InvalidSourceUrlError


def validate_video_id(video_id: str) -> str:
    if not video_id or any(character in video_id for character in {"/", "\\", "\x00"}):
        raise InvalidSourceUrlError
    return video_id
