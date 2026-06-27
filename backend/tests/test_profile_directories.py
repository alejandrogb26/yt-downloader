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
async def test_create_directory_in_root(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"name": "Clasicos"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "name": "Clasicos",
        "path": "Clasicos",
        "type": "directory",
    }
    assert (library_root / "Clasicos").is_dir()


@pytest.mark.anyio
async def test_create_directory_inside_subdirectory(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "Rock").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"parent_path": "Rock", "name": "Clasicos"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "name": "Clasicos",
        "path": "Rock/Clasicos",
        "type": "directory",
    }
    assert (library_root / "Rock" / "Clasicos").is_dir()


@pytest.mark.anyio
async def test_create_directory_returns_404_for_unknown_profile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/manolo/directories",
        json={"name": "Clasicos"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
async def test_create_directory_returns_404_for_disabled_profile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(
        monkeypatch,
        tmp_path,
        [profile_config(library_root, enabled=False)],
    )

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"name": "Clasicos"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name",
    ["", "   ", "Bad/Name", r"Bad\Name", ".", "..", ".hidden", "bad\x00name"],
)
async def test_create_directory_rejects_invalid_names(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"name": name},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid directory name."}


@pytest.mark.anyio
@pytest.mark.parametrize("parent_path", ["/tmp", "..", r"Rock\Clasicos"])
async def test_create_directory_rejects_invalid_parent_paths(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    parent_path: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"parent_path": parent_path, "name": "Clasicos"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid directory path."}


@pytest.mark.anyio
async def test_create_directory_returns_404_for_missing_parent(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"parent_path": "missing", "name": "Clasicos"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Directory not found."}


@pytest.mark.anyio
async def test_create_directory_returns_422_when_parent_is_file(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "Rock").write_bytes(b"file")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"parent_path": "Rock", "name": "Clasicos"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested path is not a directory."}


@pytest.mark.anyio
async def test_create_directory_returns_409_when_directory_exists(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "Clasicos").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"name": "Clasicos"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "An entry with this name already exists."}


@pytest.mark.anyio
async def test_create_directory_returns_409_when_file_exists(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "Clasicos").write_bytes(b"file")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"name": "Clasicos"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "An entry with this name already exists."}


@pytest.mark.anyio
async def test_create_directory_cannot_use_symlink_parent(
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

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"parent_path": "linked", "name": "Clasicos"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Directory not found."}
    assert not (target / "Clasicos").exists()


@pytest.mark.anyio
async def test_create_directory_returns_503_when_profile_root_is_unavailable(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing-library"
    configure_profiles(monkeypatch, tmp_path, [profile_config(missing_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"name": "Clasicos"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Profile storage is unavailable."}


@pytest.mark.anyio
async def test_create_directory_response_never_exposes_root_path(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/directories",
        json={"name": "Clasicos"},
    )

    assert response.status_code == 201
    assert str(library_root) not in response.text
    assert "root_path" not in response.text
    assert not response.json()["path"].startswith("/")
