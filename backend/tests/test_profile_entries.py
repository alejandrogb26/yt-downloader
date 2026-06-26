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
) -> Path:
    config_path = tmp_path / "profiles.json"
    config_path.write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
    monkeypatch.setenv("PROFILES_CONFIG_PATH", str(config_path))
    get_settings.cache_clear()
    return config_path


def profile_config(root_path: Path, enabled: bool = True) -> dict[str, object]:
    return {
        "id": "pepe",
        "display_name": "Pepe",
        "root_path": str(root_path),
        "enabled": enabled,
    }


@pytest.mark.anyio
async def test_entries_lists_library_root(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "Rock").mkdir()
    (library_root / "song.mp3").write_bytes(b"abc")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get("/api/v1/profiles/pepe/entries")

    assert response.status_code == 200
    assert response.json() == {
        "profile": {"id": "pepe", "display_name": "Pepe"},
        "path": "",
        "entries": [
            {
                "name": "Rock",
                "path": "Rock",
                "type": "directory",
                "size_bytes": None,
            },
            {
                "name": "song.mp3",
                "path": "song.mp3",
                "type": "file",
                "size_bytes": 3,
            },
        ],
    }


@pytest.mark.anyio
async def test_entries_lists_subdirectory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    rock = library_root / "Rock"
    classics = rock / "Clasicos"
    classics.mkdir(parents=True)
    (rock / "cancion.mp3").write_bytes(b"12345")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get(
        "/api/v1/profiles/pepe/entries", params={"path": "Rock"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "profile": {"id": "pepe", "display_name": "Pepe"},
        "path": "Rock",
        "entries": [
            {
                "name": "Clasicos",
                "path": "Rock/Clasicos",
                "type": "directory",
                "size_bytes": None,
            },
            {
                "name": "cancion.mp3",
                "path": "Rock/cancion.mp3",
                "type": "file",
                "size_bytes": 5,
            },
        ],
    }


@pytest.mark.anyio
async def test_entries_sort_directories_before_files_case_insensitive(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "zeta.mp3").write_bytes(b"1")
    (library_root / "Beta").mkdir()
    (library_root / "alpha.mp3").write_bytes(b"1")
    (library_root / "alpha").mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get("/api/v1/profiles/pepe/entries")

    assert response.status_code == 200
    assert [entry["name"] for entry in response.json()["entries"]] == [
        "alpha",
        "Beta",
        "alpha.mp3",
        "zeta.mp3",
    ]


@pytest.mark.anyio
async def test_entries_hides_dotfiles_and_dot_directories(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / ".hidden-dir").mkdir()
    (library_root / ".hidden-file").write_bytes(b"hidden")
    (library_root / "visible.mp3").write_bytes(b"visible")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get("/api/v1/profiles/pepe/entries")

    assert response.status_code == 200
    assert [entry["name"] for entry in response.json()["entries"]] == ["visible.mp3"]


@pytest.mark.anyio
async def test_entries_hides_symlinks_and_blocks_symlink_navigation(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    symlink_path = library_root / "linked"
    try:
        symlink_path.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    list_response = await client.get("/api/v1/profiles/pepe/entries")
    navigate_response = await client.get(
        "/api/v1/profiles/pepe/entries",
        params={"path": "linked"},
    )

    assert list_response.status_code == 200
    assert list_response.json()["entries"] == []
    assert navigate_response.status_code == 404
    assert navigate_response.json() == {"detail": "Directory not found."}


@pytest.mark.anyio
async def test_entries_rejects_absolute_path(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get(
        "/api/v1/profiles/pepe/entries", params={"path": "/tmp"}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid directory path."}


@pytest.mark.anyio
async def test_entries_rejects_parent_directory_path(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get("/api/v1/profiles/pepe/entries", params={"path": ".."})

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid directory path."}


@pytest.mark.anyio
async def test_entries_rejects_backslash_path(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get(
        "/api/v1/profiles/pepe/entries",
        params={"path": r"Rock\Clasicos"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid directory path."}


@pytest.mark.anyio
async def test_entries_returns_404_for_unknown_profile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get("/api/v1/profiles/manolo/entries")

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
async def test_entries_returns_404_for_disabled_profile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(
        monkeypatch, tmp_path, [profile_config(library_root, enabled=False)]
    )

    response = await client.get("/api/v1/profiles/pepe/entries")

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
async def test_entries_returns_404_for_missing_directory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get(
        "/api/v1/profiles/pepe/entries",
        params={"path": "missing"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Directory not found."}


@pytest.mark.anyio
async def test_entries_returns_422_when_path_points_to_file(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get(
        "/api/v1/profiles/pepe/entries",
        params={"path": "song.mp3"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested path is not a directory."}


@pytest.mark.anyio
async def test_entries_returns_503_when_profile_root_is_unavailable(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing-library"
    configure_profiles(monkeypatch, tmp_path, [profile_config(missing_root)])

    response = await client.get("/api/v1/profiles/pepe/entries")

    assert response.status_code == 503
    assert response.json() == {"detail": "Profile storage is unavailable."}


@pytest.mark.anyio
async def test_entries_never_exposes_root_path(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"song")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.get("/api/v1/profiles/pepe/entries")

    assert response.status_code == 200
    assert str(library_root) not in response.text
    assert "root_path" not in response.text
