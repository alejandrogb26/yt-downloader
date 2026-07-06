import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from yt_downloader_api.api.routes import health as health_module
from yt_downloader_api.core.config import get_settings
from yt_downloader_api.main import app


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()


class FakeReadySession:
    def __enter__(self) -> FakeReadySession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _statement: object) -> FakeReadySession:
        return self

    def scalar_one(self) -> int:
        return 1


class FailingReadySession(FakeReadySession):
    def execute(self, _statement: object) -> FailingReadySession:
        raise SQLAlchemyError("simulated database failure")


def configure_ready_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profiles_body: object | None = None,
    exclusions_body: object | None = None,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        json.dumps(
            profiles_body
            if profiles_body is not None
            else {
                "profiles": [
                    {
                        "id": "pepe",
                        "display_name": "Pepe",
                        "root_path": str(tmp_path / "library"),
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    exclusions_path = tmp_path / "library-exclusions.json"
    exclusions_path.write_text(
        json.dumps(
            exclusions_body
            if exclusions_body is not None
            else {"excluded_names": ["@eaDir"]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://user:pass@host:3306/db")
    monkeypatch.setenv("PROFILES_CONFIG_PATH", str(profiles_path))
    monkeypatch.setenv("LIBRARY_EXCLUSIONS_CONFIG_PATH", str(exclusions_path))
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_health_check_returns_ok() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "yt-downloader-api",
        "environment": "development",
    }


@pytest.mark.anyio
async def test_readiness_returns_ready_with_database_and_valid_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_ready_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        health_module,
        "get_session_factory",
        lambda: lambda: FakeReadySession(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "ok",
            "profiles_config": "ok",
            "library_exclusions_config": "ok",
        },
    }


@pytest.mark.anyio
async def test_readiness_returns_503_when_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_ready_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        health_module,
        "get_session_factory",
        lambda: lambda: FailingReadySession(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"
    assert "mysql" not in response.text
    assert str(tmp_path) not in response.text


@pytest.mark.anyio
async def test_readiness_returns_503_when_profiles_file_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_ready_environment(
        monkeypatch, tmp_path, profiles_body={"profiles": "bad"}
    )
    monkeypatch.setattr(
        health_module,
        "get_session_factory",
        lambda: lambda: FakeReadySession(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["profiles_config"] == "invalid"
    assert str(tmp_path) not in response.text


@pytest.mark.anyio
async def test_readiness_returns_503_when_exclusions_config_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_ready_environment(
        monkeypatch, tmp_path, exclusions_body={"excluded_names": [""]}
    )
    monkeypatch.setattr(
        health_module,
        "get_session_factory",
        lambda: lambda: FakeReadySession(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["library_exclusions_config"] == "invalid"
    assert str(tmp_path) not in response.text


@pytest.mark.anyio
async def test_liveness_stays_ok_when_readiness_dependency_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://user:pass@host:3306/db")
    monkeypatch.setattr(
        health_module,
        "get_session_factory",
        lambda: lambda: FailingReadySession(),
    )
    get_settings.cache_clear()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
