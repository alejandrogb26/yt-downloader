import httpx
import pytest

from yt_downloader_api.core.config import Settings, get_settings
from yt_downloader_api.db import session as db_session
from yt_downloader_api.db.base import Base
from yt_downloader_api.db.models import AudioPolicy, DownloadJobStatus
from yt_downloader_api.main import app, create_app


def test_settings_can_load_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings()

    assert settings.database_url is None
    assert settings.database_pool_size == 5
    assert settings.database_max_overflow == 5
    assert settings.database_pool_recycle_seconds == 1800


def test_engine_configuration_is_created_only_when_requested() -> None:
    settings = Settings(
        database_url="mysql+pymysql://user:password@127.0.0.1:3306/app?charset=utf8mb4",
        database_pool_size=7,
        database_max_overflow=3,
        database_pool_recycle_seconds=900,
    )

    engine = db_session.create_engine_from_settings(settings)

    assert engine.url.drivername == "mysql+pymysql"
    assert engine.pool.size() == 7
    assert engine.pool._max_overflow == 3
    assert engine.pool._recycle == 900
    assert engine.pool._pre_ping is True


@pytest.mark.anyio
async def test_health_works_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
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


def test_metadata_contains_download_tables() -> None:
    assert set(Base.metadata.tables) >= {"download_jobs", "download_job_events"}


def test_download_jobs_columns_and_indexes() -> None:
    table = Base.metadata.tables["download_jobs"]

    assert set(table.columns.keys()) >= {
        "id",
        "profile_id",
        "source_url",
        "destination_relative_path",
        "requested_filename",
        "audio_policy",
        "status",
        "progress_percent",
        "title",
        "output_relative_path",
        "source_format_id",
        "source_container",
        "source_audio_codec",
        "output_container",
        "output_audio_codec",
        "transcode_applied",
        "error_code",
        "error_message",
        "worker_id",
        "attempt_count",
        "created_at",
        "updated_at",
        "heartbeat_at",
        "started_at",
        "finished_at",
    }
    assert table.columns["id"].primary_key is True
    assert table.columns["profile_id"].nullable is False
    assert table.columns["source_url"].nullable is False
    assert table.columns["audio_policy"].nullable is False
    assert table.columns["status"].nullable is False
    assert table.columns["transcode_applied"].nullable is False
    assert table.columns["attempt_count"].nullable is False
    assert "requested_format" not in table.columns
    assert "requested_audio_quality" not in table.columns
    assert {index.name for index in table.indexes} >= {
        "ix_download_jobs_status_created_at",
        "ix_download_jobs_profile_id_created_at",
        "ix_download_jobs_status_heartbeat_at",
    }


def test_download_job_events_columns_indexes_and_foreign_key() -> None:
    table = Base.metadata.tables["download_job_events"]

    assert set(table.columns.keys()) >= {
        "id",
        "job_id",
        "created_at",
        "level",
        "message",
        "progress_percent",
    }
    assert table.columns["id"].primary_key is True
    assert table.columns["job_id"].nullable is False
    assert {index.name for index in table.indexes} >= {
        "ix_download_job_events_job_id_created_at"
    }

    foreign_keys = list(table.columns["job_id"].foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].target_fullname == "download_jobs.id"
    assert foreign_keys[0].ondelete == "CASCADE"


def test_download_jobs_profile_id_has_no_foreign_key() -> None:
    table = Base.metadata.tables["download_jobs"]

    assert not table.columns["profile_id"].foreign_keys


def test_download_job_status_enum_values() -> None:
    assert [status.value for status in DownloadJobStatus] == [
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]


def test_audio_policy_enum_values() -> None:
    assert [policy.value for policy in AudioPolicy] == ["prefer_m4a_then_best_source"]


def test_create_app_does_not_create_tables_automatically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create_all(*args: object, **kwargs: object) -> None:
        raise AssertionError("create_all must not be called")

    monkeypatch.setattr(Base.metadata, "create_all", fail_create_all)

    created_app = create_app()

    assert created_app.title == "yt-downloader API"
