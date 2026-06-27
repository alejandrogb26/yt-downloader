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


async def trash(client: httpx.AsyncClient, path: str) -> httpx.Response:
    return await client.request(
        "DELETE",
        "/api/v1/profiles/pepe/entries",
        json={"path": path},
    )


@pytest.mark.anyio
async def test_trash_file(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    source = library_root / "song.mp3"
    source.write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await trash(client, "song.mp3")

    trash_entries = list((library_root / ".trash").iterdir())
    assert response.status_code == 200
    assert response.json() == {"status": "trashed", "original_path": "song.mp3"}
    assert not source.exists()
    assert (library_root / ".trash").is_dir()
    assert len(trash_entries) == 1
    assert trash_entries[0].is_file()
    assert trash_entries[0].name.endswith("-song.mp3")


@pytest.mark.anyio
async def test_trash_directory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    source = library_root / "Rock"
    source.mkdir(parents=True)
    (source / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await trash(client, "Rock")

    trash_entries = list((library_root / ".trash").iterdir())
    assert response.status_code == 200
    assert response.json() == {"status": "trashed", "original_path": "Rock"}
    assert not source.exists()
    assert len(trash_entries) == 1
    assert trash_entries[0].is_dir()
    assert trash_entries[0].name.endswith("-Rock")
    assert (trash_entries[0] / "song.mp3").is_file()


@pytest.mark.anyio
async def test_trash_same_name_twice_does_not_collide(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    (library_root / "song.mp3").write_bytes(b"one")
    first_response = await trash(client, "song.mp3")
    (library_root / "song.mp3").write_bytes(b"two")
    second_response = await trash(client, "song.mp3")

    trash_entries = list((library_root / ".trash").iterdir())
    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(trash_entries) == 2
    assert len({entry.name for entry in trash_entries}) == 2
    assert all(entry.name.endswith("-song.mp3") for entry in trash_entries)


@pytest.mark.anyio
async def test_trash_directory_is_hidden_from_entries_listing(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])
    await trash(client, "song.mp3")

    response = await client.get("/api/v1/profiles/pepe/entries")

    assert response.status_code == 200
    assert ".trash" not in response.text
    assert response.json()["entries"] == []


@pytest.mark.anyio
async def test_trash_returns_404_for_unknown_profile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.request(
        "DELETE",
        "/api/v1/profiles/manolo/entries",
        json={"path": "song.mp3"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
async def test_trash_returns_404_for_disabled_profile(
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

    response = await trash(client, "song.mp3")

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["", "/tmp/song.mp3", "../song.mp3", r"Rock\song.mp3"])
async def test_trash_rejects_invalid_paths(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await trash(client, path)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid entry path."}


@pytest.mark.anyio
async def test_trash_returns_404_for_missing_source(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await trash(client, "missing.mp3")

    assert response.status_code == 404
    assert response.json() == {"detail": "Entry not found."}


@pytest.mark.anyio
@pytest.mark.parametrize("path", [".hidden.mp3", ".trash", ".trash/song.mp3"])
async def test_trash_rejects_not_allowed_entries(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
) -> None:
    library_root = tmp_path / "library"
    trash_dir = library_root / ".trash"
    trash_dir.mkdir(parents=True)
    (library_root / ".hidden.mp3").write_bytes(b"hidden")
    (trash_dir / "song.mp3").write_bytes(b"trashed")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await trash(client, path)

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested entry is not allowed."}


@pytest.mark.anyio
async def test_trash_rejects_symlink_entry(
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

    response = await trash(client, "linked.mp3")

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested entry is not allowed."}
    assert symlink_path.is_symlink()


@pytest.mark.anyio
async def test_trash_rejects_symlink_traversal(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "song.mp3").write_bytes(b"song")
    symlink_path = library_root / "linked"
    try:
        symlink_path.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await trash(client, "linked/song.mp3")

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested entry is not allowed."}
    assert (external / "song.mp3").is_file()


@pytest.mark.anyio
async def test_trash_returns_503_when_trash_path_is_file(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    (library_root / ".trash").write_bytes(b"not a directory")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await trash(client, "song.mp3")

    assert response.status_code == 503
    assert response.json() == {"detail": "Profile storage is unavailable."}


@pytest.mark.anyio
async def test_trash_returns_503_when_trash_path_is_symlink(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    external = tmp_path / "external-trash"
    external.mkdir()
    symlink_path = library_root / ".trash"
    try:
        symlink_path.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await trash(client, "song.mp3")

    assert response.status_code == 503
    assert response.json() == {"detail": "Profile storage is unavailable."}
    assert (library_root / "song.mp3").is_file()


@pytest.mark.anyio
async def test_trash_response_does_not_expose_root_or_trash_location(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    rock = library_root / "Rock"
    rock.mkdir(parents=True)
    (rock / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await trash(client, "Rock/song.mp3")

    assert response.status_code == 200
    assert response.json() == {
        "status": "trashed",
        "original_path": "Rock/song.mp3",
    }
    assert str(library_root) not in response.text
    assert "root_path" not in response.text
    assert ".trash" not in response.text
    assert not response.json()["original_path"].startswith("/")
