from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from yt_downloader_api.core.config import Settings, get_settings


class DatabaseConfigurationError(RuntimeError):
    """Raised when database configuration is missing or unsafe to use."""


def create_engine_from_settings(settings: Settings) -> Engine:
    if not settings.database_url:
        raise DatabaseConfigurationError("DATABASE_URL is required.")

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_recycle=settings.database_pool_recycle_seconds,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


@lru_cache
def get_engine() -> Engine:
    return create_engine_from_settings(get_settings())


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(get_engine())


def get_db_session() -> Generator[Session]:
    session_factory = get_session_factory()
    with session_factory() as session:
        yield session
