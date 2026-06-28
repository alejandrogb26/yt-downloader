from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "yt-downloader API"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8080
    profiles_config_path: str = "/etc/yt-downloader/profiles.json"
    database_url: str | None = None
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_recycle_seconds: int = 1800

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
