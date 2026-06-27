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
async def test_move_file_from_root_to_subdirectory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    target_dir = library_root / "Favoritas"
    target_dir.mkdir(parents=True)
    source = library_root / "cancion.mp3"
    source.write_bytes(b"music")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "cancion.mp3", "target_directory_path": "Favoritas"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "cancion.mp3",
        "path": "Favoritas/cancion.mp3",
        "type": "file",
        "size_bytes": 5,
    }
    assert not source.exists()
    assert (target_dir / "cancion.mp3").is_file()


@pytest.mark.anyio
async def test_move_file_from_subdirectory_to_root(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    rock = library_root / "Rock"
    rock.mkdir(parents=True)
    source = rock / "cancion.mp3"
    source.write_bytes(b"1234567")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "Rock/cancion.mp3"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "cancion.mp3",
        "path": "cancion.mp3",
        "type": "file",
        "size_bytes": 7,
    }
    assert not source.exists()
    assert (library_root / "cancion.mp3").is_file()


@pytest.mark.anyio
async def test_move_directory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    source = library_root / "Rock"
    target_dir = library_root / "Favoritas"
    source.mkdir(parents=True)
    target_dir.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "Rock", "target_directory_path": "Favoritas"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "Rock",
        "path": "Favoritas/Rock",
        "type": "directory",
        "size_bytes": None,
    }
    assert not source.exists()
    assert (target_dir / "Rock").is_dir()


@pytest.mark.anyio
async def test_move_entry_between_subdirectories(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    rock = library_root / "Rock"
    favoritas = library_root / "Favoritas"
    rock.mkdir(parents=True)
    favoritas.mkdir()
    source = rock / "cancion.mp3"
    source.write_bytes(b"audio")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "Rock/cancion.mp3", "target_directory_path": "Favoritas"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "cancion.mp3",
        "path": "Favoritas/cancion.mp3",
        "type": "file",
        "size_bytes": 5,
    }
    assert not source.exists()
    assert (favoritas / "cancion.mp3").is_file()


@pytest.mark.anyio
async def test_move_to_same_directory_returns_current_entry(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    rock = library_root / "Rock"
    rock.mkdir(parents=True)
    source = rock / "cancion.mp3"
    source.write_bytes(b"same")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "Rock/cancion.mp3", "target_directory_path": "Rock"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "cancion.mp3",
        "path": "Rock/cancion.mp3",
        "type": "file",
        "size_bytes": 4,
    }
    assert source.is_file()


@pytest.mark.anyio
async def test_move_returns_404_for_unknown_profile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/manolo/entries/move",
        json={"source_path": "song.mp3"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
async def test_move_returns_404_for_disabled_profile(
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

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "song.mp3"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "source_path",
    ["", "/tmp/song.mp3", "../song.mp3", r"Rock\song.mp3"],
)
async def test_move_rejects_invalid_source_paths(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_path: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": source_path},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid entry path."}


@pytest.mark.anyio
@pytest.mark.parametrize("target_directory_path", ["/tmp", "..", r"Rock\Clasicos"])
async def test_move_rejects_invalid_target_directory_paths(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target_directory_path: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={
            "source_path": "song.mp3",
            "target_directory_path": target_directory_path,
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid directory path."}


@pytest.mark.anyio
async def test_move_returns_404_for_missing_source(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "missing.mp3"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Entry not found."}


@pytest.mark.anyio
async def test_move_returns_404_for_missing_target_directory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "song.mp3", "target_directory_path": "missing"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Directory not found."}


@pytest.mark.anyio
async def test_move_returns_422_when_target_is_file(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    (library_root / "target.mp3").write_bytes(b"target")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "song.mp3", "target_directory_path": "target.mp3"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested path is not a directory."}


@pytest.mark.anyio
async def test_move_returns_409_for_file_collision(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    target_dir = library_root / "Favoritas"
    target_dir.mkdir(parents=True)
    source = library_root / "song.mp3"
    source.write_bytes(b"song")
    (target_dir / "song.mp3").write_bytes(b"existing")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "song.mp3", "target_directory_path": "Favoritas"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "An entry with this name already exists."}
    assert source.is_file()


@pytest.mark.anyio
async def test_move_returns_409_for_directory_collision(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    source = library_root / "Rock"
    target_dir = library_root / "Favoritas"
    source.mkdir(parents=True)
    (target_dir / "Rock").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "Rock", "target_directory_path": "Favoritas"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "An entry with this name already exists."}
    assert source.is_dir()


@pytest.mark.anyio
async def test_move_rejects_symlink_entry(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    target_dir = library_root / "Favoritas"
    target_dir.mkdir(parents=True)
    target = tmp_path / "target.mp3"
    target.write_bytes(b"target")
    symlink_path = library_root / "linked.mp3"
    try:
        symlink_path.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "linked.mp3", "target_directory_path": "Favoritas"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested entry is not allowed."}
    assert symlink_path.is_symlink()


@pytest.mark.anyio
async def test_move_rejects_symlink_source_traversal(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    target_dir = library_root / "Favoritas"
    target_dir.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "song.mp3").write_bytes(b"song")
    symlink_path = library_root / "linked"
    try:
        symlink_path.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "linked/song.mp3", "target_directory_path": "Favoritas"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested entry is not allowed."}
    assert (external / "song.mp3").is_file()


@pytest.mark.anyio
async def test_move_rejects_symlink_target_directory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    source = library_root / "song.mp3"
    source.write_bytes(b"song")
    external = tmp_path / "external"
    external.mkdir()
    symlink_path = library_root / "linked"
    try:
        symlink_path.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "song.mp3", "target_directory_path": "linked"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested directory is not allowed."}
    assert source.is_file()


@pytest.mark.anyio
async def test_move_rejects_directory_into_itself(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "Rock").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "Rock", "target_directory_path": "Rock"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Cannot move a directory into itself."}
    assert (library_root / "Rock").is_dir()


@pytest.mark.anyio
async def test_move_rejects_directory_into_child_directory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "Rock" / "Clasicos").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "Rock", "target_directory_path": "Rock/Clasicos"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Cannot move a directory into itself."}
    assert (library_root / "Rock" / "Clasicos").is_dir()


@pytest.mark.anyio
async def test_move_response_never_exposes_root_path(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    target_dir = library_root / "Favoritas"
    target_dir.mkdir(parents=True)
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/entries/move",
        json={"source_path": "song.mp3", "target_directory_path": "Favoritas"},
    )

    assert response.status_code == 200
    assert str(library_root) not in response.text
    assert "root_path" not in response.text
    assert not response.json()["path"].startswith("/")
