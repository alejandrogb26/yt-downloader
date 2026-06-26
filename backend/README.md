# yt-downloader API

Backend FastAPI inicial para `yt-downloader`.

## Desarrollo

```bash
uv sync --project backend
uv run --project backend pytest
uv run --project backend ruff check .
uv run --project backend ruff format --check .
uv run --project backend uvicorn yt_downloader_api.main:app --host 127.0.0.1 --port 8080 --reload
```
