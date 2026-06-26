import httpx
import pytest

from yt_downloader_api.main import app


@pytest.mark.anyio
async def test_health_check_returns_ok() -> None:
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
