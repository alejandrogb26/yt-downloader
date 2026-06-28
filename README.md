# yt-downloader

`yt-downloader` será una aplicación para gestionar descargas de vídeo mediante una API propia, un frontend separado y procesos de descarga en segundo plano.

## Arquitectura prevista

- `frontend`: aplicación web separada para operar el sistema.
- `backend`: API HTTP con FastAPI y Pydantic v2.
- Worker de descargas: proceso independiente para ejecutar descargas y actualizar estados.
- MariaDB: base de datos relacional para trabajos de descarga, eventos e historial.
- Almacenamiento NFS: destino compartido para los archivos descargados.

Actualmente está implementada la base de la API en `backend`, la exposición de perfiles de biblioteca configurados por JSON, la navegación de bibliotecas, la creación segura de directorios, el renombrado seguro de ficheros/directorios, el movimiento de entradas dentro de un mismo perfil, el envío de entradas a papelera y la base ORM/Alembic para persistir futuros trabajos de descarga. No se incluye Docker, workers, yt-dlp, frontend, Caddy ni systemd.

## Perfiles de biblioteca

Los perfiles definen bibliotecas disponibles para el sistema. Cada perfil tiene un identificador público, un nombre visible y una ruta raíz interna (`root_path`) donde estará la biblioteca.

La API `GET /api/v1/profiles` devuelve solo perfiles habilitados y nunca expone `root_path` al cliente. Las rutas reales son configuración de infraestructura.

La API `GET /api/v1/profiles/{profile_id}/entries` permite listar la raíz de una biblioteca o navegar por subdirectorios usando rutas relativas. No sigue enlaces simbólicos, no muestra elementos ocultos que comienzan por `.` y no devuelve rutas absolutas.

La API `POST /api/v1/profiles/{profile_id}/directories` permite crear directorios dentro de la raíz configurada del perfil. La operación se limita estrictamente a rutas relativas bajo `root_path` y no permite atravesar enlaces simbólicos.

La API `PATCH /api/v1/profiles/{profile_id}/entries/rename` permite renombrar ficheros y directorios normales. El renombrado se limita al mismo directorio padre: `new_name` es solo un nombre, no una ruta, y no se acepta movimiento entre directorios.

La API `POST /api/v1/profiles/{profile_id}/entries/move` permite mover ficheros y directorios normales entre directorios de la misma biblioteca del perfil. El movimiento conserva siempre el nombre original y el destino debe ser un directorio existente dentro del mismo perfil.

La API `DELETE /api/v1/profiles/{profile_id}/entries` no borra definitivamente. Mueve ficheros y directorios normales a una papelera interna `.trash` dentro de la raíz del perfil. Esa carpeta no se expone en los listados normales.

Límites actuales: no hay borrado definitivo, vaciado de papelera, restauración, endpoints de descargas, worker ni autenticación.

## Persistencia

MariaDB será la persistencia para trabajos de descarga, eventos e historial. No sustituye al sistema de archivos: las bibliotecas y los archivos siguen viviendo en NFS bajo las rutas de cada perfil.

El esquema se aplica con Alembic. La API no crea tablas al arrancar y `GET /api/v1/health` funciona aunque `DATABASE_URL` no esté configurada.

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

Comandos Alembic:

```bash
uv run --project backend alembic -c backend/alembic.ini current
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend alembic -c backend/alembic.ini history
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

Crear un directorio:

```bash
curl -X POST http://127.0.0.1:8080/api/v1/profiles/pepe/directories \
  -H 'Content-Type: application/json' \
  -d '{"parent_path":"Rock","name":"Clasicos"}'
```

Renombrar una entrada:

```bash
curl -X PATCH http://127.0.0.1:8080/api/v1/profiles/pepe/entries/rename \
  -H 'Content-Type: application/json' \
  -d '{"path":"Rock/cancion-vieja.mp3","new_name":"cancion-nueva.mp3"}'
```

Mover una entrada:

```bash
curl -X POST http://127.0.0.1:8080/api/v1/profiles/pepe/entries/move \
  -H 'Content-Type: application/json' \
  -d '{"source_path":"Rock/cancion.mp3","target_directory_path":"Favoritas"}'
```

Enviar una entrada a papelera:

```bash
curl -X DELETE http://127.0.0.1:8080/api/v1/profiles/pepe/entries \
  -H 'Content-Type: application/json' \
  -d '{"path":"Rock/cancion.mp3"}'
```

## Docker

Este proyecto no usa Docker en este bloque inicial.
