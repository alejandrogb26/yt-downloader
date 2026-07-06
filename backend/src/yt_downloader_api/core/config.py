from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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
    worker_concurrency: int = 2
    worker_queue_poll_interval_seconds: int = 3
    download_staging_root: str = "/var/lib/yt-downloader/staging"
    download_progress_update_interval_seconds: int = 5
    download_progress_minimum_percent_delta: int = 1

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
