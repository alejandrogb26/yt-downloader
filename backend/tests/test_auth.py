from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from yt_downloader_api.api import dependencies
from yt_downloader_api.core.config import get_settings
from yt_downloader_api.db.base import Base
from yt_downloader_api.db.models import User, UserSession
from yt_downloader_api.main import app
from yt_downloader_api.services.auth import create_user, hash_session_token
from yt_downloader_api.services.db_profiles import (
    grant_profile_access,
    upsert_library_profile,
)
from yt_downloader_api.services.passwords import hash_password, verify_password


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def auth_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("LIBRARY_EXCLUSIONS_CONFIG_PATH", str(tmp_path / "missing.json"))
    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[dependencies.get_database_session] = override_session
    return session


def bootstrap_user_profile(
    session: Session,
    root: Path,
    username: str = "AlejandroGB",
    enabled: bool = True,
) -> User:
    user = create_user(session, username, "Alejandro", "secret", enabled=enabled)
    profile = upsert_library_profile(session, "pepe", "Pepe", str(root), True)
    grant_profile_access(session, user, profile, "owner")
    return user


@pytest.mark.real_auth
def test_password_hashing_and_verification() -> None:
    stored = hash_password("secret")

    assert stored.startswith("pbkdf2_sha256_v1:")
    assert verify_password("secret", stored)
    assert not verify_password("wrong", stored)
    assert "secret" not in stored


@pytest.mark.anyio
@pytest.mark.real_auth
async def test_login_me_and_logout_with_secure_cookie(
    auth_db: Session,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    bootstrap_user_profile(auth_db, root)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://testserver"
    ) as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"username": "alejandrogb", "password": "secret", "remember_me": True},
        )
        assert login_response.status_code == 200
        assert "httponly" in login_response.headers["set-cookie"].lower()
        assert "secure" in login_response.headers["set-cookie"].lower()
        assert "samesite=lax" in login_response.headers["set-cookie"].lower()
        body = login_response.json()
        assert body["user"]["username"] == "alejandrogb"
        assert body["profiles"] == [{"id": "pepe", "display_name": "Pepe"}]
        assert "password_hash" not in login_response.text

        me_response = await client.get("/api/v1/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["csrf_token"] == body["csrf_token"]

        logout_response = await client.post("/api/v1/auth/logout")
        assert logout_response.status_code == 200
        assert "max-age=0" in logout_response.headers["set-cookie"].lower()
        assert auth_db.scalars(select(UserSession)).first().revoked_at is not None


@pytest.mark.anyio
@pytest.mark.real_auth
async def test_login_rejects_bad_password_disabled_and_expired_session(
    auth_db: Session,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    user = bootstrap_user_profile(auth_db, root)
    disabled = bootstrap_user_profile(auth_db, root, username="disabled", enabled=False)
    assert disabled.enabled is False

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://testserver"
    ) as client:
        bad_response = await client.post(
            "/api/v1/auth/login",
            json={"username": user.username, "password": "bad", "remember_me": False},
        )
        assert bad_response.status_code == 401
        assert bad_response.json()["detail"] == "Usuario o contraseña incorrectos."

        disabled_response = await client.post(
            "/api/v1/auth/login",
            json={"username": "disabled", "password": "secret", "remember_me": False},
        )
        assert disabled_response.status_code == 401

        token = "expired-token"
        now = datetime.now(UTC)
        auth_db.add(
            UserSession(
                id="00000000-0000-4000-8000-000000000010",
                user_id=user.id,
                session_token_hash=hash_session_token(token),
                remember_me=False,
                created_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
                last_seen_at=now - timedelta(hours=2),
                revoked_at=None,
                user_agent=None,
                ip_address=None,
            )
        )
        auth_db.commit()
        client.cookies.set("yt_downloader_session", token, domain="testserver")
        expired_response = await client.get("/api/v1/auth/me")
        assert expired_response.status_code == 401


@pytest.mark.anyio
@pytest.mark.real_auth
async def test_profiles_filtering_and_csrf_required(
    auth_db: Session,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    bootstrap_user_profile(auth_db, root)
    upsert_library_profile(auth_db, "hidden", "Hidden", str(root), True)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://testserver"
    ) as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "username": "alejandrogb",
                "password": "secret",
                "remember_me": False,
            },
        )
        csrf_token = login_response.json()["csrf_token"]

        profiles_response = await client.get("/api/v1/profiles")
        assert profiles_response.json() == {
            "profiles": [{"id": "pepe", "display_name": "Pepe"}]
        }

        forbidden_response = await client.post(
            "/api/v1/profiles/pepe/directories",
            json={"parent_path": "", "name": "Rock"},
        )
        assert forbidden_response.status_code == 403

        created_response = await client.post(
            "/api/v1/profiles/pepe/directories",
            headers={"X-CSRF-Token": csrf_token},
            json={"parent_path": "", "name": "Rock"},
        )
        assert created_response.status_code == 201

        hidden_response = await client.get("/api/v1/profiles/hidden/entries")
        assert hidden_response.status_code == 404
