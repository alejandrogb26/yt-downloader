# yt-downloader

`yt-downloader` será una aplicación para gestionar descargas de vídeo mediante una API propia, un frontend separado y procesos de descarga en segundo plano.

## Arquitectura prevista

- `frontend`: aplicación web separada para operar el sistema.
- `backend`: API HTTP con FastAPI y Pydantic v2.
- Worker de descargas: proceso independiente para ejecutar descargas y actualizar estados.
- MariaDB: base de datos relacional para persistencia.
- Almacenamiento NFS: destino compartido para los archivos descargados.

Actualmente está implementada la base de la API en `backend`, la exposición de perfiles de biblioteca configurados por JSON y la navegación de solo lectura por el contenido de esas bibliotecas. No se incluye Docker, MariaDB, workers, yt-dlp, frontend, Caddy ni systemd.

## Perfiles de biblioteca

Los perfiles definen bibliotecas disponibles para el sistema. Cada perfil tiene un identificador público, un nombre visible y una ruta raíz interna (`root_path`) donde estará la biblioteca.

La API `GET /api/v1/profiles` devuelve solo perfiles habilitados y nunca expone `root_path` al cliente. Las rutas reales son configuración de infraestructura.

La API `GET /api/v1/profiles/{profile_id}/entries` permite listar la raíz de una biblioteca o navegar por subdirectorios usando rutas relativas. No sigue enlaces simbólicos, no muestra elementos ocultos que comienzan por `.` y no devuelve rutas absolutas.

Límites actuales: no hay operaciones de escritura, no hay descargas, no hay base de datos y no hay autenticación.

Hay un ejemplo versionable en `config/profiles.example.json`. El fichero real `config/profiles.json` está ignorado por Git.

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

Levantar la API usando el ejemplo de perfiles local, sin modificar `/etc`:

```bash
PROFILES_CONFIG_PATH="$PWD/config/profiles.example.json" uv run --project backend uvicorn yt_downloader_api.main:app --host 127.0.0.1 --port 8080 --reload
```

Comprobar health check:

```bash
curl http://127.0.0.1:8080/api/v1/health
```

Comprobar perfiles:

```bash
curl http://127.0.0.1:8080/api/v1/profiles
```

Comprobar navegación de una biblioteca:

```bash
curl http://127.0.0.1:8080/api/v1/profiles/pepe/entries
curl 'http://127.0.0.1:8080/api/v1/profiles/pepe/entries?path=Rock'
```

## Docker

Este proyecto no usa Docker en este bloque inicial.
