import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from yt_downloader_api.api import dependencies
from yt_downloader_api.core.config import get_settings
from yt_downloader_api.db.base import Base
from yt_downloader_api.main import app
from yt_downloader_api.services.auth import create_user
from yt_downloader_api.services.db_profiles import (
    grant_profile_access,
    upsert_library_profile,
)


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
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
    root_path: Path,
) -> None:
    config_path = tmp_path / "profiles.json"
    config_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "pepe",
                        "display_name": "Pepe",
                        "root_path": str(root_path),
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROFILES_CONFIG_PATH", str(config_path))
    get_settings.cache_clear()


def make_audio_file(root: Path, relative_path: str = "Rock/song.m4a") -> Path:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"original-audio")
    return target


def fake_subprocess_run(calls: list[list[str]], fail_ffmpeg: bool = False):
    def run(command: list[str], **_kwargs: Any):
        calls.append(command)
        if command[0] == "ffprobe" and "format=duration" in command:
            return FakeCompleted(stdout="180.0\n")
        if command[0] == "ffprobe" and "format_tags" in command:
            return FakeCompleted(
                stdout=json.dumps({"format": {"tags": {"title": "Viejo"}}})
            )
        if command[0] == "ffmpeg":
            output_path = Path(command[-1])
            if fail_ffmpeg:
                output_path.write_bytes(b"partial")
                return FakeCompleted(returncode=1)
            output_path.write_bytes(b"edited-audio")
            return FakeCompleted()
        return FakeCompleted(returncode=1)

    return run


class FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = "private stderr"


@pytest.mark.anyio
async def test_trim_audio_uses_copy_and_creates_output_without_overwrite(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    source = make_audio_file(root)
    configure_profiles(monkeypatch, tmp_path, root)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "yt_downloader_api.services.audio_operations.subprocess.run",
        fake_subprocess_run(calls),
    )

    response = await client.post(
        "/api/v1/profiles/pepe/audio/trim",
        json={
            "source_path": "Rock/song.m4a",
            "start": "00:00:30",
            "end": "00:02:10",
            "output_filename": "song recortada",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "path": "Rock/song recortada.m4a",
        "name": "song recortada.m4a",
        "operation": "trim",
    }
    assert source.read_bytes() == b"original-audio"
    assert (root / "Rock/song recortada.m4a").read_bytes() == b"edited-audio"
    ffmpeg_call = next(call for call in calls if call[0] == "ffmpeg")
    assert "-c:a" in ffmpeg_call
    assert ffmpeg_call[ffmpeg_call.index("-c:a") + 1] == "copy"
    assert not any(codec in ffmpeg_call for codec in ["aac", "libmp3lame", "opus"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("start", "end"),
    [("bad", "00:01"), ("00:02", "00:01"), ("00:00", "00:04:00")],
)
async def test_trim_rejects_invalid_times(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    start: str,
    end: str,
) -> None:
    root = tmp_path / "library"
    make_audio_file(root)
    configure_profiles(monkeypatch, tmp_path, root)
    monkeypatch.setattr(
        "yt_downloader_api.services.audio_operations.subprocess.run",
        fake_subprocess_run([]),
    )

    response = await client.post(
        "/api/v1/profiles/pepe/audio/trim",
        json={"source_path": "Rock/song.m4a", "start": start, "end": end},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Los tiempos de recorte no son válidos."}


@pytest.mark.anyio
@pytest.mark.parametrize("source_path", ["/tmp/song.m4a", "../song.m4a"])
async def test_audio_operations_reject_unsafe_paths(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_path: str,
) -> None:
    root = tmp_path / "library"
    make_audio_file(root)
    configure_profiles(monkeypatch, tmp_path, root)

    response = await client.patch(
        "/api/v1/profiles/pepe/audio/metadata",
        json={"source_path": source_path, "metadata": {"title": "Nuevo"}},
    )

    assert response.status_code == 422
    assert "root_path" not in response.text


@pytest.mark.anyio
async def test_audio_operations_reject_hidden_and_symlink(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    hidden = make_audio_file(root, ".hidden/song.m4a")
    configure_profiles(monkeypatch, tmp_path, root)
    symlink = root / "linked.m4a"
    try:
        symlink.symlink_to(hidden)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")

    hidden_response = await client.patch(
        "/api/v1/profiles/pepe/audio/metadata",
        json={"source_path": ".hidden/song.m4a", "metadata": {"title": "Nuevo"}},
    )
    symlink_response = await client.patch(
        "/api/v1/profiles/pepe/audio/metadata",
        json={"source_path": "linked.m4a", "metadata": {"title": "Nuevo"}},
    )

    assert hidden_response.status_code == 422
    assert symlink_response.status_code == 422


@pytest.mark.anyio
async def test_trim_ffmpeg_failure_is_safe_and_cleans_temporary(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    source = make_audio_file(root)
    configure_profiles(monkeypatch, tmp_path, root)
    monkeypatch.setattr(
        "yt_downloader_api.services.audio_operations.subprocess.run",
        fake_subprocess_run([], fail_ffmpeg=True),
    )

    response = await client.post(
        "/api/v1/profiles/pepe/audio/trim",
        json={"source_path": "Rock/song.m4a", "start": "0", "end": "10"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "No se pudo completar la operación de audio."}
    assert source.read_bytes() == b"original-audio"
    assert list((root / "Rock").glob(".yt-downloader-*")) == []
    assert "private stderr" not in response.text


@pytest.mark.anyio
async def test_metadata_updates_only_allowed_fields_with_copy_codec(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    source = make_audio_file(root)
    configure_profiles(monkeypatch, tmp_path, root)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "yt_downloader_api.services.audio_operations.subprocess.run",
        fake_subprocess_run(calls),
    )

    response = await client.patch(
        "/api/v1/profiles/pepe/audio/metadata",
        json={
            "source_path": "Rock/song.m4a",
            "metadata": {"title": "Nuevo", "artist": "Artista", "genre": ""},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "path": "Rock/song.m4a",
        "name": "song.m4a",
        "operation": "metadata",
    }
    assert source.read_bytes() == b"edited-audio"
    ffmpeg_call = next(call for call in calls if call[0] == "ffmpeg")
    assert "-c" in ffmpeg_call
    assert ffmpeg_call[ffmpeg_call.index("-c") + 1] == "copy"
    assert "-metadata" in ffmpeg_call
    assert "title=Nuevo" in ffmpeg_call


@pytest.mark.anyio
async def test_metadata_rejects_unknown_or_too_long_fields(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    make_audio_file(root)
    configure_profiles(monkeypatch, tmp_path, root)

    unknown_response = await client.patch(
        "/api/v1/profiles/pepe/audio/metadata",
        json={"source_path": "Rock/song.m4a", "metadata": {"comment": "No"}},
    )
    long_response = await client.patch(
        "/api/v1/profiles/pepe/audio/metadata",
        json={"source_path": "Rock/song.m4a", "metadata": {"title": "x" * 201}},
    )

    assert unknown_response.status_code == 422
    assert long_response.status_code == 422
    assert unknown_response.json() == {
        "detail": "Los metadatos enviados no son válidos."
    }


@pytest.mark.anyio
async def test_get_metadata_returns_allowed_public_fields(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    make_audio_file(root)
    configure_profiles(monkeypatch, tmp_path, root)
    monkeypatch.setattr(
        "yt_downloader_api.services.audio_operations.subprocess.run",
        fake_subprocess_run([]),
    )

    response = await client.get(
        "/api/v1/profiles/pepe/audio/metadata",
        params={"path": "Rock/song.m4a"},
    )

    assert response.status_code == 200
    assert response.json() == {"path": "Rock/song.m4a", "metadata": {"title": "Viejo"}}
    assert "root_path" not in response.text


@pytest.mark.anyio
@pytest.mark.real_auth
async def test_audio_mutation_requires_authorized_profile_and_csrf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    root = tmp_path / "library"
    root.mkdir()
    make_audio_file(root)
    other_root = tmp_path / "other"
    other_root.mkdir()
    user = create_user(session, "alejandro", "Alejandro", "secret")
    profile = upsert_library_profile(session, "pepe", "Pepe", str(root), True)
    upsert_library_profile(session, "other", "Other", str(other_root), True)
    grant_profile_access(session, user, profile, "owner")
    monkeypatch.setenv("LIBRARY_EXCLUSIONS_CONFIG_PATH", str(tmp_path / "missing.json"))
    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[dependencies.get_database_session] = override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://testserver"
    ) as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"username": "alejandro", "password": "secret", "remember_me": False},
        )
        csrf_token = login_response.json()["csrf_token"]
        missing_csrf_response = await client.patch(
            "/api/v1/profiles/pepe/audio/metadata",
            json={"source_path": "Rock/song.m4a", "metadata": {"title": "Nuevo"}},
        )
        unauthorized_response = await client.patch(
            "/api/v1/profiles/other/audio/metadata",
            headers={"X-CSRF-Token": csrf_token},
            json={"source_path": "song.m4a", "metadata": {"title": "Nuevo"}},
        )

    assert missing_csrf_response.status_code == 403
    assert unauthorized_response.status_code == 404
    app.dependency_overrides.clear()
