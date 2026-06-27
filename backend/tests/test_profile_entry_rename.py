import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from yt_downloader_api.core.config import get_settings
from yt_downloader_api.main import app


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as async_client:
        yield async_client


def configure_profiles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profiles: list[dict[str, object]],
) -> None:
    config_path = tmp_path / "profiles.json"
    config_path.write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
    monkeypatch.setenv("PROFILES_CONFIG_PATH", str(config_path))
    get_settings.cache_clear()


def profile_config(root_path: Path, enabled: bool = True) -> dict[str, object]:
    return {
        "id": "pepe",
        "display_name": "Pepe",
        "root_path": str(root_path),
        "enabled": enabled,
    }


@pytest.mark.anyio
async def test_rename_file_in_root(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    source = library_root / "old.mp3"
    source.write_bytes(b"music")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "old.mp3", "new_name": "new.mp3"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "new.mp3",
        "path": "new.mp3",
        "type": "file",
        "size_bytes": 5,
    }
    assert not source.exists()
    assert (library_root / "new.mp3").is_file()


@pytest.mark.anyio
async def test_rename_file_inside_subdirectory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    rock = library_root / "Rock"
    rock.mkdir(parents=True)
    source = rock / "old.mp3"
    source.write_bytes(b"1234567")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "Rock/old.mp3", "new_name": "new.mp3"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "new.mp3",
        "path": "Rock/new.mp3",
        "type": "file",
        "size_bytes": 7,
    }
    assert not source.exists()
    assert (rock / "new.mp3").is_file()


@pytest.mark.anyio
async def test_rename_directory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    source = library_root / "Old"
    source.mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "Old", "new_name": "New"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "New",
        "path": "New",
        "type": "directory",
        "size_bytes": None,
    }
    assert not source.exists()
    assert (library_root / "New").is_dir()


@pytest.mark.anyio
async def test_rename_with_same_name_returns_current_entry(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    source = library_root / "same.mp3"
    source.write_bytes(b"same")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "same.mp3", "new_name": "same.mp3"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "same.mp3",
        "path": "same.mp3",
        "type": "file",
        "size_bytes": 4,
    }
    assert source.is_file()


@pytest.mark.anyio
async def test_rename_returns_404_for_unknown_profile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/manolo/entries/rename",
        json={"path": "song.mp3", "new_name": "new.mp3"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
async def test_rename_returns_404_for_disabled_profile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(
        monkeypatch, tmp_path, [profile_config(library_root, enabled=False)]
    )

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "song.mp3", "new_name": "new.mp3"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["", "/tmp/song.mp3", "../song.mp3", r"Rock\song.mp3"])
async def test_rename_rejects_invalid_paths(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": path, "new_name": "new.mp3"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid entry path."}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "new_name",
    ["", "   ", "Bad/Name", r"Bad\Name", ".", "..", ".hidden", "bad\x00name"],
)
async def test_rename_rejects_invalid_names(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    new_name: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "song.mp3", "new_name": new_name},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid entry name."}


@pytest.mark.anyio
async def test_rename_returns_409_for_file_collision(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "old.mp3").write_bytes(b"old")
    (library_root / "existing.mp3").write_bytes(b"existing")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "old.mp3", "new_name": "existing.mp3"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "An entry with this name already exists."}


@pytest.mark.anyio
async def test_rename_returns_409_for_directory_collision(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "old.mp3").write_bytes(b"old")
    (library_root / "Existing").mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "old.mp3", "new_name": "Existing"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "An entry with this name already exists."}


@pytest.mark.anyio
async def test_rename_rejects_symlink_entry(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    target = tmp_path / "target.mp3"
    target.write_bytes(b"target")
    symlink_path = library_root / "linked.mp3"
    try:
        symlink_path.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "linked.mp3", "new_name": "new.mp3"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested entry is not allowed."}
    assert symlink_path.is_symlink()


@pytest.mark.anyio
async def test_rename_rejects_hidden_entry(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    hidden_entry = library_root / ".hidden.mp3"
    hidden_entry.write_bytes(b"hidden")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": ".hidden.mp3", "new_name": "visible.mp3"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested entry is not allowed."}
    assert hidden_entry.is_file()


@pytest.mark.anyio
async def test_rename_rejects_symlink_traversal(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (target / "song.mp3").write_bytes(b"song")
    symlink_path = library_root / "linked"
    try:
        symlink_path.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "linked/song.mp3", "new_name": "new.mp3"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested entry is not allowed."}
    assert (target / "song.mp3").is_file()


@pytest.mark.anyio
async def test_rename_response_never_exposes_root_path(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "old.mp3").write_bytes(b"old")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.patch(
        "/api/v1/profiles/pepe/entries/rename",
        json={"path": "old.mp3", "new_name": "new.mp3"},
    )

    assert response.status_code == 200
    assert str(library_root) not in response.text
    assert "root_path" not in response.text
    assert not response.json()["path"].startswith("/")
