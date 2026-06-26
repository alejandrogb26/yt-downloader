import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class InvalidDirectoryPathError(Exception):
    """Raised when a client path is not a safe relative directory path."""


class DirectoryNotFoundError(Exception):
    """Raised when the requested directory does not exist."""


class RequestedPathNotDirectoryError(Exception):
    """Raised when the requested path exists but is not a directory."""


class ProfileStorageUnavailableError(Exception):
    """Raised when profile storage cannot be used safely."""


@dataclass(frozen=True)
class FileSystemEntry:
    name: str
    path: str
    type: str
    size_bytes: int | None


def list_directory_entries(
    root_path: str, relative_path: str = ""
) -> list[FileSystemEntry]:
    root = Path(root_path)
    safe_path = validate_relative_directory_path(relative_path)
    ensure_available_root(root)
    target = resolve_directory(root, safe_path)

    try:
        entries = [entry for entry in target.iterdir() if is_listable_entry(entry)]
    except OSError as exc:
        raise ProfileStorageUnavailableError from exc

    return sorted(
        [to_file_system_entry(entry, safe_path) for entry in entries],
        key=lambda entry: (entry.type != "directory", entry.name.casefold()),
    )


def validate_relative_directory_path(relative_path: str) -> str:
    if "\x00" in relative_path or "\\" in relative_path:
        raise InvalidDirectoryPathError
    if relative_path == "":
        return ""
    if relative_path.startswith("/"):
        raise InvalidDirectoryPathError

    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InvalidDirectoryPathError

    path = PurePosixPath(relative_path)
    if path.is_absolute():
        raise InvalidDirectoryPathError
    return path.as_posix()


def ensure_available_root(root: Path) -> None:
    try:
        root_status = root.stat(follow_symlinks=False)
    except OSError as exc:
        raise ProfileStorageUnavailableError from exc

    if not stat.S_ISDIR(root_status.st_mode) or root.is_symlink():
        raise ProfileStorageUnavailableError

    try:
        for _entry in root.iterdir():
            break
    except OSError as exc:
        raise ProfileStorageUnavailableError from exc


def resolve_directory(root: Path, relative_path: str) -> Path:
    current = root
    if relative_path == "":
        return current

    for part in relative_path.split("/"):
        current = current / part
        try:
            current_status = current.stat(follow_symlinks=False)
        except FileNotFoundError as exc:
            raise DirectoryNotFoundError from exc
        except OSError as exc:
            raise ProfileStorageUnavailableError from exc

        if current.is_symlink():
            raise DirectoryNotFoundError
        if not stat.S_ISDIR(current_status.st_mode):
            raise RequestedPathNotDirectoryError

    return current


def is_listable_entry(entry: Path) -> bool:
    if entry.name.startswith(".") or entry.is_symlink():
        return False
    try:
        entry_status = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(entry_status.st_mode) or stat.S_ISREG(entry_status.st_mode)


def to_file_system_entry(entry: Path, parent_relative_path: str) -> FileSystemEntry:
    entry_status = entry.stat(follow_symlinks=False)
    entry_type = "directory" if stat.S_ISDIR(entry_status.st_mode) else "file"
    relative_path = join_relative_path(parent_relative_path, entry.name)
    return FileSystemEntry(
        name=entry.name,
        path=relative_path,
        type=entry_type,
        size_bytes=None if entry_type == "directory" else entry_status.st_size,
    )


def join_relative_path(parent_relative_path: str, name: str) -> str:
    if parent_relative_path == "":
        return name
    return f"{parent_relative_path}/{name}"
