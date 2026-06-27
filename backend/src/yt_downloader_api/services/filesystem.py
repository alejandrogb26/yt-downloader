import stat
from dataclasses import dataclass
from os import W_OK, X_OK, access
from pathlib import Path, PurePosixPath


class InvalidDirectoryPathError(Exception):
    """Raised when a client path is not a safe relative directory path."""


class InvalidEntryPathError(Exception):
    """Raised when a client entry path is not a safe relative entry path."""


class DirectoryNotFoundError(Exception):
    """Raised when the requested directory does not exist."""


class EntryNotFoundError(Exception):
    """Raised when the requested entry does not exist."""


class RequestedPathNotDirectoryError(Exception):
    """Raised when the requested path exists but is not a directory."""


class RequestedEntryNotAllowedError(Exception):
    """Raised when the requested entry exists but cannot be operated on."""


class ProfileStorageUnavailableError(Exception):
    """Raised when profile storage cannot be used safely."""


class InvalidDirectoryNameError(Exception):
    """Raised when a client directory name is not safe."""


class EntryAlreadyExistsError(Exception):
    """Raised when a target entry already exists."""


@dataclass(frozen=True)
class FileSystemEntry:
    name: str
    path: str
    type: str
    size_bytes: int | None


@dataclass(frozen=True)
class CreatedDirectory:
    name: str
    path: str
    type: str = "directory"


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


def create_directory(root_path: str, parent_path: str, name: str) -> CreatedDirectory:
    root = Path(root_path)
    safe_parent_path = validate_relative_directory_path(parent_path)
    safe_name = validate_directory_name(name)
    ensure_writable_root(root)
    parent = resolve_directory(root, safe_parent_path)
    target = parent / safe_name

    try:
        target.stat(follow_symlinks=False)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ProfileStorageUnavailableError from exc
    else:
        raise EntryAlreadyExistsError

    try:
        target.mkdir(mode=0o755)
    except FileExistsError as exc:
        raise EntryAlreadyExistsError from exc
    except OSError as exc:
        raise ProfileStorageUnavailableError from exc

    return CreatedDirectory(
        name=safe_name,
        path=join_relative_path(safe_parent_path, safe_name),
    )


def rename_entry(root_path: str, relative_path: str, new_name: str) -> FileSystemEntry:
    root = Path(root_path)
    safe_path = validate_relative_entry_path(relative_path)
    safe_name = validate_directory_name(new_name)
    ensure_writable_root(root)

    source = resolve_entry(root, safe_path)
    parent_path = get_parent_relative_path(safe_path)
    target = source.parent / safe_name

    if source.name == safe_name:
        return to_file_system_entry(source, parent_path)

    try:
        target.stat(follow_symlinks=False)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ProfileStorageUnavailableError from exc
    else:
        raise EntryAlreadyExistsError

    try:
        source.rename(target)
    except FileNotFoundError as exc:
        raise EntryNotFoundError from exc
    except FileExistsError as exc:
        raise EntryAlreadyExistsError from exc
    except OSError as exc:
        raise ProfileStorageUnavailableError from exc

    return to_file_system_entry(target, parent_path)


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


def validate_relative_entry_path(relative_path: str) -> str:
    if relative_path == "":
        raise InvalidEntryPathError
    try:
        return validate_relative_directory_path(relative_path)
    except InvalidDirectoryPathError as exc:
        raise InvalidEntryPathError from exc


def validate_directory_name(name: str) -> str:
    if (
        not name.strip()
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or name in {".", ".."}
        or name.startswith(".")
        or len(name) > 128
    ):
        raise InvalidDirectoryNameError
    return name


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


def ensure_writable_root(root: Path) -> None:
    ensure_available_root(root)
    if not access(root, W_OK | X_OK):
        raise ProfileStorageUnavailableError


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


def resolve_entry(root: Path, relative_path: str) -> Path:
    parts = relative_path.split("/")
    parent = root
    for part in parts[:-1]:
        parent = parent / part
        try:
            parent_status = parent.stat(follow_symlinks=False)
        except FileNotFoundError as exc:
            raise EntryNotFoundError from exc
        except OSError as exc:
            raise ProfileStorageUnavailableError from exc

        if parent.is_symlink():
            raise RequestedEntryNotAllowedError
        if not stat.S_ISDIR(parent_status.st_mode):
            raise RequestedEntryNotAllowedError

    entry = parent / parts[-1]
    if entry.name.startswith("."):
        raise RequestedEntryNotAllowedError

    try:
        entry_status = entry.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise EntryNotFoundError from exc
    except OSError as exc:
        raise ProfileStorageUnavailableError from exc

    if entry.is_symlink():
        raise RequestedEntryNotAllowedError
    if not (stat.S_ISDIR(entry_status.st_mode) or stat.S_ISREG(entry_status.st_mode)):
        raise RequestedEntryNotAllowedError
    return entry


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


def get_parent_relative_path(relative_path: str) -> str:
    parent = PurePosixPath(relative_path).parent.as_posix()
    if parent == ".":
        return ""
    return parent
