from types import SimpleNamespace

import pytest

from yt_downloader_api.api import dependencies
from yt_downloader_api.api.routes import downloads as downloads_routes
from yt_downloader_api.api.routes import profiles as profiles_routes
from yt_downloader_api.db.models import User
from yt_downloader_api.main import app
from yt_downloader_api.models.profiles import LibraryProfile
from yt_downloader_api.services import download_execution
from yt_downloader_api.services.db_profiles import ProfilePersistenceError
from yt_downloader_api.services.profiles import (
    ProfilesConfigurationError,
    load_enabled_profile,
    load_enabled_profiles,
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "real_auth: exercise production authentication dependencies"
    )


@pytest.fixture(autouse=True)
def authenticated_legacy_api(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
):
    if request.node.get_closest_marker("real_auth") is not None:
        yield
        return

    user = User(
        id="00000000-0000-4000-8000-000000000001",
        username="test-user",
        password_hash="not-used",
        display_name="Test User",
        enabled=True,
        is_admin=True,
        created_at=None,  # type: ignore[arg-type]
        updated_at=None,  # type: ignore[arg-type]
        last_login_at=None,
    )
    context = dependencies.AuthContext(
        session=SimpleNamespace(),  # type: ignore[arg-type]
        auth=SimpleNamespace(user=user, token="test-token", session=None),
    )

    def fake_auth_context():
        return context

    def fake_csrf_context():
        return context

    def fake_load_authenticated_session(_session, _token):
        return context.auth

    def fake_verify_csrf_token(_session_token, _csrf_token):
        return True

    def fake_list_authorized_profiles(_session, _user):
        from yt_downloader_api.core.config import get_settings

        try:
            return load_enabled_profiles(get_settings().profiles_config_path)
        except ProfilesConfigurationError as exc:
            if "test_download_queries" in request.node.nodeid:
                return [
                    LibraryProfile(
                        id="pepe",
                        display_name="Pepe",
                        root_path="/tmp/pepe",
                        enabled=True,
                    ),
                    LibraryProfile(
                        id="ana",
                        display_name="Ana",
                        root_path="/tmp/ana",
                        enabled=True,
                    ),
                ]
            raise ProfilePersistenceError from exc

    def fake_get_authorized_profile(
        _session,
        _user,
        profile_slug: str,
        require_write: bool = False,
    ):
        from yt_downloader_api.core.config import get_settings

        try:
            return load_enabled_profile(
                get_settings().profiles_config_path, profile_slug
            )
        except ProfilesConfigurationError as exc:
            raise ProfilePersistenceError from exc

    def fake_load_enabled_profiles(_session):
        config_path = getattr(_session, "profiles_config_path", None)
        if config_path is None:
            from yt_downloader_api.core.config import get_settings

            config_path = get_settings().profiles_config_path
        return load_enabled_profiles(config_path)

    def fake_load_enabled_profile(_session, profile_slug: str):
        config_path = getattr(_session, "profiles_config_path", None)
        if config_path is None:
            from yt_downloader_api.core.config import get_settings

            config_path = get_settings().profiles_config_path
        return load_enabled_profile(config_path, profile_slug)

    class FakeSession:
        profiles_config_path: str | None = None

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_session_factory():
        return FakeSession()

    def fake_db_session_generator():
        yield FakeSession()

    app.dependency_overrides[dependencies.get_auth_context] = fake_auth_context
    app.dependency_overrides[dependencies.require_csrf_token] = fake_csrf_context
    monkeypatch.setattr(
        dependencies, "load_authenticated_session", fake_load_authenticated_session
    )
    monkeypatch.setattr(dependencies, "verify_csrf_token", fake_verify_csrf_token)
    monkeypatch.setattr(dependencies, "get_db_session", fake_db_session_generator)
    monkeypatch.setattr(
        profiles_routes, "list_authorized_profiles", fake_list_authorized_profiles
    )
    monkeypatch.setattr(
        profiles_routes, "get_authorized_profile", fake_get_authorized_profile
    )
    monkeypatch.setattr(
        downloads_routes, "list_authorized_profiles", fake_list_authorized_profiles
    )
    monkeypatch.setattr(
        downloads_routes, "get_authorized_profile", fake_get_authorized_profile
    )
    monkeypatch.setattr(
        download_execution, "load_enabled_profiles", fake_load_enabled_profiles
    )
    monkeypatch.setattr(
        download_execution, "load_enabled_profile", fake_load_enabled_profile
    )
    monkeypatch.setattr(
        download_execution, "get_session_factory", lambda: fake_session_factory
    )
    yield
    app.dependency_overrides.clear()
