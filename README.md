# yt-downloader

`yt-downloader` será una aplicación para gestionar descargas de vídeo mediante una API propia, un frontend separado y procesos de descarga en segundo plano.

## Arquitectura prevista

- `frontend`: aplicación web separada para operar el sistema.
- `backend`: API HTTP con FastAPI y Pydantic v2.
- Worker de descargas: proceso independiente para ejecutar descargas y actualizar estados.
- MariaDB: base de datos relacional para persistencia.
- Almacenamiento NFS: destino compartido para los archivos descargados.

En este bloque inicial solo está implementada la base de la API en `backend`. No se incluye Docker, MariaDB, workers, yt-dlp, frontend, Caddy ni systemd.

## Requisitos

- Python 3.14
- `uv`

## Comandos de desarrollo

Instalar dependencias:

```bash
uv sync --project backend
```

Ejecutar pruebas:

```bash
uv run --project backend pytest
```

Ejecutar Ruff:

```bash
uv run --project backend ruff check .
uv run --project backend ruff format --check .
```

Levantar la API en desarrollo:

```bash
uv run --project backend uvicorn yt_downloader_api.main:app --host 127.0.0.1 --port 8080 --reload
```

Comprobar health check:

```bash
curl http://127.0.0.1:8080/api/v1/health
```

## Docker

Este proyecto no usa Docker en este bloque inicial.
