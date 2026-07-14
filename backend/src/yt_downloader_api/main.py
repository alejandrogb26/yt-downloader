from fastapi import FastAPI

from yt_downloader_api.api.routes.auth import router as auth_router
from yt_downloader_api.api.routes.downloads import router as downloads_router
from yt_downloader_api.api.routes.health import router as health_router
from yt_downloader_api.api.routes.profiles import router as profiles_router
from yt_downloader_api.core.config import get_settings

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(downloads_router, prefix=API_PREFIX)
    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(profiles_router, prefix=API_PREFIX)
    return app


app = create_app()
