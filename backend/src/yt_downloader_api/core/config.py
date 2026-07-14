from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "yt-downloader API"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8080
    profiles_config_path: str = "/etc/yt-downloader/profiles.json"
    library_exclusions_config_path: str = "/etc/yt-downloader/library-exclusions.json"
    database_url: str | None = None
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_recycle_seconds: int = 1800
    worker_id: str | None = None
    worker_stale_job_timeout_seconds: int = 900
    worker_heartbeat_interval_seconds: int = 30
    worker_concurrency: int = 2
    worker_queue_poll_interval_seconds: int = 3
    download_staging_root: str = "/var/lib/yt-downloader/staging"
    download_progress_update_interval_seconds: int = 5
    download_progress_minimum_percent_delta: int = 1
    yt_dlp_max_attempts: int = 3
    yt_dlp_retry_initial_delay_seconds: int = 2
    session_cookie_name: str = "yt_downloader_session"
    session_cookie_secure: bool = True
    session_cookie_samesite: str = "lax"
    session_idle_timeout_seconds: int = 43200
    session_remember_me_timeout_seconds: int = 2592000
    session_token_bytes: int = 32

    @field_validator("download_staging_root")
    @classmethod
    def validate_download_staging_root(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("download_staging_root must be absolute")
        return value

    @field_validator("worker_concurrency")
    @classmethod
    def validate_worker_concurrency(cls, value: int) -> int:
        if value < 1 or value > 4:
            raise ValueError("worker_concurrency must be between 1 and 4")
        return value

    @field_validator("worker_queue_poll_interval_seconds")
    @classmethod
    def validate_worker_queue_poll_interval_seconds(cls, value: int) -> int:
        if value < 1 or value > 60:
            raise ValueError(
                "worker_queue_poll_interval_seconds must be between 1 and 60"
            )
        return value

    @field_validator("worker_stale_job_timeout_seconds")
    @classmethod
    def validate_worker_stale_job_timeout_seconds(cls, value: int) -> int:
        if value < 2:
            raise ValueError("worker_stale_job_timeout_seconds must be at least 2")
        return value

    @field_validator("worker_heartbeat_interval_seconds")
    @classmethod
    def validate_worker_heartbeat_interval_seconds(cls, value: int) -> int:
        if value < 1:
            raise ValueError("worker_heartbeat_interval_seconds must be positive")
        return value

    @field_validator("yt_dlp_max_attempts")
    @classmethod
    def validate_yt_dlp_max_attempts(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("yt_dlp_max_attempts must be between 1 and 5")
        return value

    @field_validator("yt_dlp_retry_initial_delay_seconds")
    @classmethod
    def validate_yt_dlp_retry_initial_delay_seconds(cls, value: int) -> int:
        if value < 1 or value > 300:
            raise ValueError(
                "yt_dlp_retry_initial_delay_seconds must be between 1 and 300"
            )
        return value

    @field_validator("session_cookie_samesite")
    @classmethod
    def validate_session_cookie_samesite(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("session_cookie_samesite must be lax, strict, or none")
        return normalized

    @field_validator(
        "session_idle_timeout_seconds",
        "session_remember_me_timeout_seconds",
        "session_token_bytes",
    )
    @classmethod
    def validate_positive_session_settings(cls, value: int) -> int:
        if value < 1:
            raise ValueError("session settings must be positive")
        return value

    @model_validator(mode="after")
    def validate_worker_heartbeat_is_before_stale_timeout(self) -> Self:
        if (
            self.worker_heartbeat_interval_seconds
            >= self.worker_stale_job_timeout_seconds
        ):
            raise ValueError(
                "worker_heartbeat_interval_seconds must be lower than "
                "worker_stale_job_timeout_seconds"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
