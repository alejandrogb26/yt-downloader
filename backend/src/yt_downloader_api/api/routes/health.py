from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from yt_downloader_api.core.config import get_settings
from yt_downloader_api.db.session import DatabaseConfigurationError, get_session_factory
from yt_downloader_api.services.library_exclusions import (
    LibraryExclusionsConfigurationError,
    load_library_excluded_names,
)
from yt_downloader_api.services.profiles import (
    ProfilesConfigurationError,
    load_profiles_config,
)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="yt-downloader-api",
        environment=settings.app_env,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness_check(response: Response) -> ReadinessResponse:
    checks = {
        "database": check_database(),
        "profiles_config": check_profiles_config(),
        "library_exclusions_config": check_library_exclusions_config(),
    }
    if all(value == "ok" for value in checks.values()):
        return ReadinessResponse(status="ready", checks=checks)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="not_ready", checks=checks)


def check_database() -> str:
    try:
        session_factory = get_session_factory()
        with session_factory() as session:
            session.execute(text("SELECT 1")).scalar_one()
    except DatabaseConfigurationError, SQLAlchemyError, RuntimeError:
        return "unavailable"
    return "ok"


def check_profiles_config() -> str:
    try:
        load_profiles_config(get_settings().profiles_config_path)
    except ProfilesConfigurationError:
        return "invalid"
    return "ok"


def check_library_exclusions_config() -> str:
    try:
        load_library_excluded_names(get_settings().library_exclusions_config_path)
    except LibraryExclusionsConfigurationError:
        return "invalid"
    return "ok"
