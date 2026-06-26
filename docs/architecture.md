# Arquitectura

`yt-downloader` se plantea como un monorepo con componentes separados para interfaz web, API, procesos de descarga, persistencia y despliegue.

## Componentes previstos

- Frontend: aplicación web separada para gestionar descargas y consultar estados. No implementado todavía.
- Backend: API FastAPI con Pydantic v2. Actualmente incluye configuración base, `GET /api/v1/health`, `GET /api/v1/profiles` y navegación de solo lectura con `GET /api/v1/profiles/{profile_id}/entries`.
- Worker de descargas: proceso independiente para ejecutar descargas con yt-dlp. No implementado todavía.
- MariaDB: base de datos para perfiles, trabajos, estados y metadatos. No implementada todavía.
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

La navegación actual es de solo lectura. Solo se listan ficheros y directorios normales; se ocultan elementos cuyo nombre empieza por `.` y enlaces simbólicos. Tampoco se permite navegar a través de enlaces simbólicos.

El sistema de archivos NFS será la fuente de verdad de las bibliotecas. Todavía no hay operaciones de escritura, descargas con yt-dlp, worker ni persistencia en MariaDB.

## Estado actual

La parte funcional actual es el backend en `backend`, ejecutable con Uvicorn en `127.0.0.1:8080`.

No hay Dockerfiles ni `docker-compose` en este bloque.
