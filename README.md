# yt-downloader

`yt-downloader` será una aplicación para gestionar descargas de vídeo mediante una API propia, un frontend separado y procesos de descarga en segundo plano.

## Arquitectura prevista

- `frontend`: aplicación web separada para operar el sistema.
- `backend`: API HTTP con FastAPI y Pydantic v2.
- Worker de descargas: proceso independiente para ejecutar descargas y actualizar estados.
- MariaDB: base de datos relacional para trabajos de descarga, eventos e historial.
- Almacenamiento NFS: destino compartido para los archivos descargados.

Actualmente está implementada la base de la API en `backend`, la exposición de perfiles de biblioteca configurados por JSON, la navegación de bibliotecas, la búsqueda global por perfil, exclusiones de biblioteca, operaciones seguras sobre entradas, la base ORM/Alembic, trabajos individuales, descargas por lote, consulta de trabajos/eventos, un worker persistente concurrente, un frontend React separado y plantillas de despliegue sin Docker en `infra/`. El frontend permite crear trabajos, crear lotes, listar la biblioteca, seleccionar destino, crear carpetas, renombrar entradas, mover entradas dentro del perfil y enviar entradas a papelera. No se incluye autenticación, cancelación ni reintentos automáticos.

Topología de despliegue prevista en LAN con CT LXC:

```text
Cliente
  ↓ HTTPS 443
Nginx central
  ↓ HTTP interno TCP 8081
Caddy en CT
  ├── frontend estático
  └── /api/* -> FastAPI 127.0.0.1:8080
                    ↓
                 MariaDB externa
                    ↑
worker systemd persistente -> staging local -> NFS por perfil
```

El DNS interno `music.alejandrogb.local` debe resolver al Nginx central, no al CT. Nginx termina HTTPS con el certificado gestionado por el administrador y reenvía HTTP interno al CT en TCP `8081`. Caddy no usa certificados y debe escuchar solo en la IP real del CT. FastAPI escucha solo en `127.0.0.1:8080`. No expongas el servicio a Internet mientras no exista autenticación y una política de seguridad completa.

## Perfiles de biblioteca

Los perfiles definen bibliotecas disponibles para el sistema. Cada perfil tiene un identificador público, un nombre visible y una ruta raíz interna (`root_path`) donde estará la biblioteca. En despliegue, cada perfil puede tener su propio montaje NFS, por ejemplo `/mnt/music/alejandrogb` y `/mnt/music/pepe`; `/mnt/music` puede ser solo el directorio padre local.

La API `GET /api/v1/profiles` devuelve solo perfiles habilitados y nunca expone `root_path` al cliente. Las rutas reales son configuración de infraestructura.

La API `GET /api/v1/profiles/{profile_id}/entries` permite listar la raíz de una biblioteca o navegar por subdirectorios usando rutas relativas. No sigue enlaces simbólicos, no muestra elementos ocultos que comienzan por `.` y no devuelve rutas absolutas.

La API `POST /api/v1/profiles/{profile_id}/directories` permite crear directorios dentro de la raíz configurada del perfil. La operación se limita estrictamente a rutas relativas bajo `root_path` y no permite atravesar enlaces simbólicos.

La API `PATCH /api/v1/profiles/{profile_id}/entries/rename` permite renombrar ficheros y directorios normales. El renombrado se limita al mismo directorio padre: `new_name` es solo un nombre, no una ruta, y no se acepta movimiento entre directorios.

La API `POST /api/v1/profiles/{profile_id}/entries/move` permite mover ficheros y directorios normales entre directorios de la misma biblioteca del perfil. El movimiento conserva siempre el nombre original y el destino debe ser un directorio existente dentro del mismo perfil.

La API `DELETE /api/v1/profiles/{profile_id}/entries` no borra definitivamente. Mueve ficheros y directorios normales a una papelera interna `.trash` dentro de la raíz del perfil. Esa carpeta no se expone en los listados normales ni en el frontend.

La API `POST /api/v1/downloads` registra un trabajo de descarga en MariaDB con estado inicial `queued`, pero no descarga desde el proceso HTTP. También se pueden listar trabajos, consultar su detalle y ver sus eventos.

El worker reclama como máximo un trabajo `queued`, lo marca como `running`, descarga una única pista de audio con la librería Python `yt-dlp`, publica el fichero final en la biblioteca y termina. Al arrancar también marca como `failed` los trabajos `running` cuyo heartbeat sea demasiado antiguo.

Límites actuales: no hay borrado definitivo, vaciado de papelera, restauración, autenticación, conversión MP3/FLAC, metadatos embebidos, carátulas, playlists ni postprocesado.

## Persistencia

MariaDB será la persistencia para trabajos de descarga, eventos e historial. No sustituye al sistema de archivos: las bibliotecas y los archivos siguen viviendo en NFS bajo las rutas de cada perfil.

La política inicial de descarga es solo audio, sin recodificación por defecto. El selector fijo de `yt-dlp` es `bestaudio[ext=m4a]/bestaudio`: se prioriza una pista M4A directa y, si no existe, se descarga el mejor audio disponible conservando el formato fuente. M4A es una preferencia de descarga, no una conversión forzada a M4A, MP3 o FLAC.

MariaDB almacena la política solicitada y el formato técnico realmente obtenido: contenedor, códec, formato fuente y si se aplicó transcodificación. En esta versión `transcode_applied` permanece siempre en `false`.

El worker descarga primero en staging local (`DOWNLOAD_STAGING_ROOT`, por defecto `/var/lib/yt-downloader/staging`) bajo un directorio único por trabajo. Solo cuando la descarga termina correctamente copia el fichero a un temporal oculto dentro del destino NFS del perfil y lo publica sin sobrescribir archivos existentes. El staging no debe estar dentro de ninguna biblioteca de perfil ni bajo `/mnt/music`.

El esquema se aplica con Alembic. La API no crea tablas al arrancar y `GET /api/v1/health` funciona aunque `DATABASE_URL` no esté configurada. `GET /api/v1/health/ready` comprueba de forma ligera MariaDB y la configuración de perfiles/exclusiones para saber si la aplicación está lista para operar.

Hay un ejemplo versionable en `config/profiles.example.json`. El fichero real `config/profiles.json` está ignorado por Git. Las exclusiones administradas del navegador de biblioteca se configuran con `LIBRARY_EXCLUSIONS_CONFIG_PATH`; en producción apunta a `/etc/yt-downloader/library-exclusions.json` y hay un ejemplo en `infra/config/library-exclusions.json.example`.

## Requisitos

- Python 3.14
- `uv`
- Node.js compatible con Vite
- `npm`

`yt-dlp` se instala mediante las dependencias Python del proyecto. Para máxima compatibilidad con YouTube, el administrador puede necesitar `yt-dlp-ejs` y un runtime JavaScript compatible. `ffmpeg` y `ffprobe` no son necesarios para esta descarga directa sin conversión, aunque pueden ser necesarios en funciones futuras de postprocesado o compatibilidad.

## Comandos de desarrollo

Instalar dependencias:

```bash
uv sync --project backend
npm install --prefix frontend
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

Levantar el frontend React/Vite en desarrollo:

```bash
npm run dev --prefix frontend
```

En desarrollo, Vite reenvía `/api` a `http://127.0.0.1:8080`, evitando CORS sin modificar FastAPI. En producción se espera publicar el build estático del frontend y la API bajo el mismo origen mediante Caddy; las plantillas de despliegue están en `infra/`.

Ejecutar verificaciones frontend:

```bash
npm run test:run --prefix frontend
npm run lint --prefix frontend
npm run build --prefix frontend
```

El build del frontend queda en `frontend/dist/` y puede servirse con Caddy usando las plantillas de `infra/`.

Ejecutar una pasada manual del worker con `--once`:

```bash
uv run --project backend python -m yt_downloader_api.worker.main --once
```

`--once` existe para diagnóstico o ejecución manual: recupera stale jobs, procesa como máximo un trabajo y sale. No es el mecanismo operativo de producción.

El worker persistente requiere `DATABASE_URL`, `PROFILES_CONFIG_PATH` y acceso de escritura a `DOWNLOAD_STAGING_ROOT` y a la biblioteca destino. No aplica migraciones automáticamente. Para fijar un identificador estable se puede configurar `WORKER_ID`; si falta, se genera uno a partir del hostname. En producción la concurrencia global del proceso se configura con `WORKER_CONCURRENCY`, el sondeo con `WORKER_QUEUE_POLL_INTERVAL_SECONDS`, el heartbeat autónomo con `WORKER_HEARTBEAT_INTERVAL_SECONDS` y la recuperación de trabajos obsoletos con `WORKER_STALE_JOB_TIMEOUT_SECONDS`. El intervalo de heartbeat debe ser positivo y menor que el timeout stale.

Ante SIGTERM, systemd solicita parada ordenada: el worker deja de reclamar trabajos nuevos y espera a que terminen los trabajos activos. Mientras espera, cada trabajo activo mantiene su heartbeat autónomo. `TimeoutStopSec` en la unidad limita cuánto puede durar esa espera antes de que systemd fuerce la terminación.

Levantar la API usando el ejemplo de perfiles local, sin modificar `/etc`:

```bash
PROFILES_CONFIG_PATH="$PWD/config/profiles.example.json" uv run --project backend uvicorn yt_downloader_api.main:app --host 127.0.0.1 --port 8080 --reload
```

Comprobar liveness y readiness:

```bash
curl http://127.0.0.1:8080/api/v1/health
curl http://127.0.0.1:8080/api/v1/health/ready
```

`/api/v1/health` es un liveness barato: no depende de MariaDB ni de NFS. `/api/v1/health/ready` comprueba conectividad ligera con MariaDB y validación de configuración de perfiles y exclusiones; no recorre NFS, no ejecuta migraciones y no contacta YouTube.

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

Registrar un trabajo de descarga en cola:

```bash
curl -X POST http://127.0.0.1:8080/api/v1/downloads \
  -H 'Content-Type: application/json' \
  -d '{"profile_id":"pepe","source_url":"https://www.youtube.com/watch?v=VIDEO_ID","destination_path":"Rock/Clasicos"}'
```

Consultar trabajos y eventos:

```bash
curl 'http://127.0.0.1:8080/api/v1/downloads?limit=25&offset=0'
curl http://127.0.0.1:8080/api/v1/downloads/JOB_UUID
curl 'http://127.0.0.1:8080/api/v1/downloads/JOB_UUID/events?limit=50&offset=0'
```

Secuencia manual de descarga:

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend uvicorn yt_downloader_api.main:app --host 127.0.0.1 --port 8080
curl -X POST http://127.0.0.1:8080/api/v1/downloads \
  -H 'Content-Type: application/json' \
  -d '{"profile_id":"pepe","source_url":"https://www.youtube.com/watch?v=VIDEO_ID","destination_path":"Rock/Clasicos"}'
uv run --project backend python -m yt_downloader_api.worker.main --once
```

## Docker

Este proyecto no usa Docker. Las plantillas de despliegue para CT LXC están en `infra/` e incluyen ejemplos de Caddy, systemd y entorno privado.
