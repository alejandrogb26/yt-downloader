# Arquitectura

`yt-downloader` se plantea como un monorepo con componentes separados para interfaz web, API, procesos de descarga, persistencia y despliegue.

## Componentes previstos

- Frontend: aplicación web separada para gestionar descargas y consultar estados. No implementado todavía.
- Backend: API FastAPI con Pydantic v2. En este bloque solo incluye configuración base y `GET /api/v1/health`.
- Worker de descargas: proceso independiente para ejecutar descargas con yt-dlp. No implementado todavía.
- MariaDB: base de datos para perfiles, trabajos, estados y metadatos. No implementada todavía.
- Almacenamiento NFS: ubicación compartida para archivos descargados. No implementado todavía.
- Infraestructura: configuración futura para servicios del sistema y proxy. No implementada todavía.

## Estado actual

La única parte funcional es la base del backend en `backend`, ejecutable con Uvicorn en `127.0.0.1:8080`.

No hay Dockerfiles ni `docker-compose` en este bloque.
