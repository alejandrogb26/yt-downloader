import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from yt_downloader_api.core.config import get_settings
from yt_downloader_api.main import app


def write_profiles_config(config_path: Path, profiles: list[dict[str, object]]) -> None:
    config_path.write_text(
        json.dumps({"profiles": profiles}),
        encoding="utf-8",
    )


def use_profiles_config(monkeypatch: pytest.MonkeyPatch, config_path: Path) -> None:
    monkeypatch.setenv("PROFILES_CONFIG_PATH", str(config_path))
    get_settings.cache_clear()


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


@pytest.mark.anyio
async def test_profiles_lists_only_enabled_profiles(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "profiles.json"
    write_profiles_config(
        config_path,
        [
            {
                "id": "pepe",
                "display_name": "Pepe",
                "root_path": "/mnt/music/pepe",
                "enabled": True,
            },
            {
                "id": "manolo",
                "display_name": "Manolo",
                "root_path": "/mnt/music/manolo",
                "enabled": False,
            },
        ],
    )
    use_profiles_config(monkeypatch, config_path)

    response = await client.get("/api/v1/profiles")

    assert response.status_code == 200
    assert response.json() == {
        "profiles": [
            {
                "id": "pepe",
                "display_name": "Pepe",
            }
        ]
    }


@pytest.mark.anyio
async def test_profiles_never_exposes_root_path(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "profiles.json"
    write_profiles_config(
        config_path,
        [
            {
                "id": "pepe",
                "display_name": "Pepe",
                "root_path": "/mnt/music/pepe",
                "enabled": True,
            }
        ],
    )
    use_profiles_config(monkeypatch, config_path)

    response = await client.get("/api/v1/profiles")

    assert response.status_code == 200
    assert "root_path" not in response.text


@pytest.mark.anyio
async def test_profiles_returns_503_for_missing_file(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_profiles_config(monkeypatch, tmp_path / "missing.json")

    response = await client.get("/api/v1/profiles")

    assert response.status_code == 503
    assert response.json() == {"detail": "Profiles configuration is unavailable."}


@pytest.mark.anyio
async def test_profiles_returns_503_for_invalid_json(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "profiles.json"
    config_path.write_text("{invalid", encoding="utf-8")
    use_profiles_config(monkeypatch, config_path)

    response = await client.get("/api/v1/profiles")

    assert response.status_code == 503
    assert response.json() == {"detail": "Profiles configuration is unavailable."}


@pytest.mark.anyio
async def test_profiles_returns_503_for_duplicate_ids(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "profiles.json"
    write_profiles_config(
        config_path,
        [
            {
                "id": "pepe",
                "display_name": "Pepe",
                "root_path": "/mnt/music/pepe",
                "enabled": True,
            },
            {
                "id": "pepe",
                "display_name": "Pepe 2",
                "root_path": "/mnt/music/pepe-2",
                "enabled": True,
            },
        ],
    )
    use_profiles_config(monkeypatch, config_path)

    response = await client.get("/api/v1/profiles")

    assert response.status_code == 503
    assert response.json() == {"detail": "Profiles configuration is unavailable."}


@pytest.mark.anyio
async def test_profiles_returns_503_for_relative_root_path(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "profiles.json"
    write_profiles_config(
        config_path,
        [
            {
                "id": "pepe",
                "display_name": "Pepe",
                "root_path": "mnt/music/pepe",
                "enabled": True,
            }
        ],
    )
    use_profiles_config(monkeypatch, config_path)

    response = await client.get("/api/v1/profiles")

    assert response.status_code == 503
    assert response.json() == {"detail": "Profiles configuration is unavailable."}
