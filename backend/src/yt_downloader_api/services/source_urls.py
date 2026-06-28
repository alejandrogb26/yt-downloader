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
    if (
        parsed_url.scheme != "https"
        or not host
        or host not in ALLOWED_YOUTUBE_HOSTS
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.port not in {None, 443}
    ):
        raise InvalidSourceUrlError

    query = parse_qs(parsed_url.query, keep_blank_values=True)
    if "list" in query:
        raise InvalidSourceUrlError

    if host in YOUTUBE_WATCH_HOSTS:
        validate_youtube_path(parsed_url.path, query)
    elif host in YOUTU_BE_HOSTS:
        validate_youtu_be_path(parsed_url.path)
    else:
        raise InvalidSourceUrlError

    return source_url


def validate_youtube_path(path: str, query: dict[str, list[str]]) -> None:
    if path == "/watch" and query.get("v", [""])[0]:
        return

    path_parts = [part for part in path.split("/") if part]
    if len(path_parts) == 2 and path_parts[0] in {"shorts", "live", "embed"}:
        return

    raise InvalidSourceUrlError


def validate_youtu_be_path(path: str) -> None:
    path_parts = [part for part in path.split("/") if part]
    if len(path_parts) == 1:
        return
    raise InvalidSourceUrlError
