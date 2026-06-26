from fastapi import APIRouter
from pydantic import BaseModel

from yt_downloader_api.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="yt-downloader-api",
        environment=settings.app_env,
    )
