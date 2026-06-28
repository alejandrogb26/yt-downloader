# Arquitectura

`yt-downloader` se plantea como un monorepo con componentes separados para interfaz web, API, procesos de descarga, persistencia y despliegue.

## Componentes previstos

- Frontend: aplicación web separada para gestionar descargas y consultar estados. No implementado todavía.
- Backend: API FastAPI con Pydantic v2. Actualmente incluye configuración base, `GET /api/v1/health`, `GET /api/v1/profiles`, navegación con `GET /api/v1/profiles/{profile_id}/entries`, creación de directorios con `POST /api/v1/profiles/{profile_id}/directories`, renombrado con `PATCH /api/v1/profiles/{profile_id}/entries/rename`, movimiento con `POST /api/v1/profiles/{profile_id}/entries/move` y envío a papelera con `DELETE /api/v1/profiles/{profile_id}/entries`.
- Worker de descargas: proceso independiente para ejecutar descargas con yt-dlp. No implementado todavía.
- MariaDB: base de datos para trabajos de descarga, eventos, estados e historial. La capa ORM y las migraciones iniciales ya están preparadas.
- Almacenamiento NFS: ubicación compartida para archivos descargados. No implementado todavía.
- Infraestructura: configuración futura para servicios del sistema y proxy. No implementada todavía.

## Perfiles de biblioteca

Los perfiles se definen en un fichero JSON externo (`profiles.json`) indicado por la variable de entorno `PROFILES_CONFIG_PATH`. Su valor por defecto es `/etc/yt-downloader/profiles.json`.

Este fichero es configuración de infraestructura: contiene las rutas raíz reales de cada biblioteca y no debe exponerse al cliente. La API solo devuelve `id` y `display_name` de perfiles habilitados.

El ejemplo versionable vive en `config/profiles.example.json`. Para desarrollo local puede usarse así, sin modificar `/etc`:

```bash
PROFILES_CONFIG_PATH="$PWD/config/profiles.example.json" uv run --project backend uvicorn yt_downloader_api.main:app --host 127.0.0.1 --port 8080 --reload
```

## Navegación de bibliotecas

`/mnt/music` será un montaje NFS en el servidor. Cada perfil apunta a una raíz interna dentro de ese montaje mediante `root_path`.

La API de navegación usa siempre rutas relativas al `root_path` del perfil. El cliente nunca recibe rutas reales del sistema, rutas absolutas ni el valor de `root_path`.

Solo se listan ficheros y directorios normales; se ocultan elementos cuyo nombre empieza por `.` y enlaces simbólicos. Tampoco se permite navegar a través de enlaces simbólicos.

La creación de directorios está limitada estrictamente a la raíz del perfil configurado. La API valida rutas relativas y nombres de directorio antes de tocar el sistema de archivos, no usa comandos externos y no expone rutas absolutas.

El renombrado de ficheros y directorios se limita al mismo directorio padre. El campo `new_name` se trata únicamente como nombre de entrada, no como ruta, por lo que no permite mover elementos entre directorios.

El movimiento de ficheros y directorios se limita a la misma biblioteca del perfil. Conserva el nombre original y solo acepta como destino un directorio existente bajo la raíz configurada del perfil.

La eliminación actual no borra definitivamente. Mueve la entrada a `.trash` dentro de la raíz del perfil, usando un nombre interno único. La API no devuelve la ubicación interna en papelera y `.trash` no aparece en los listados normales porque las entradas ocultas no se exponen.

El sistema de archivos NFS será la fuente de verdad de las bibliotecas. Todavía no hay borrado definitivo, vaciado de papelera, restauración, descargas con yt-dlp ni worker.

## Persistencia y flujo futuro

La API FastAPI usará MariaDB para registrar trabajos de descarga y consultar sus eventos. El worker futuro también usará MariaDB para tomar trabajos, actualizar estado y registrar progreso.

Flujo previsto:

```text
FastAPI API -> MariaDB
Worker futuro -> MariaDB
Worker futuro -> staging local -> NFS
```

MariaDB no sustituye a NFS. Los archivos descargados y las bibliotecas seguirán viviendo en el sistema de archivos montado; MariaDB almacenará trabajos, estados, eventos y metadatos operativos.

El esquema se gestiona con Alembic. No se crean tablas automáticamente al iniciar FastAPI.

Flujo actual para registrar un trabajo:

```text
Cliente -> FastAPI -> validación de perfil y destino NFS -> MariaDB
```

La API solo registra el trabajo en cola. No ejecuta yt-dlp, FFmpeg ni procesos externos.

## Worker Futuro

El worker futuro descargará solo audio. La política inicial será priorizar una pista M4A directa y, si no existe, conservar el mejor audio disponible sin recodificar.

Comportamiento previsto:

- Selecciona solo audio.
- Prioriza M4A.
- Conserva el formato fuente si no hay M4A.
- No recodifica por defecto.
- Registra el formato real obtenido.

La compatibilidad de formatos de fallback con Audio Station se comprobará más adelante. No hay conversión de compatibilidad en esta fase.

## Estado actual

La parte funcional actual es el backend en `backend`, ejecutable con Uvicorn en `127.0.0.1:8080`.

No hay Dockerfiles ni `docker-compose` en este bloque.
