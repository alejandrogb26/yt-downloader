# Arquitectura

`yt-downloader` se plantea como un monorepo con componentes separados para interfaz web, API, procesos de descarga, persistencia y despliegue.

## Componentes previstos

- Frontend: aplicación web separada para gestionar descargas y consultar estados. No implementado todavía.
- Backend: API FastAPI con Pydantic v2. Actualmente incluye configuración base, `GET /api/v1/health` y `GET /api/v1/profiles`.
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

El sistema de archivos NFS será la fuente de verdad de las bibliotecas. En este bloque no se exploran directorios ni se comprueba si las rutas existen o son accesibles.

## Estado actual

La parte funcional actual es el backend en `backend`, ejecutable con Uvicorn en `127.0.0.1:8080`.

No hay Dockerfiles ni `docker-compose` en este bloque.
