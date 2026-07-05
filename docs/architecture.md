# Arquitectura

`yt-downloader` se plantea como un monorepo con componentes separados para interfaz web, API, procesos de descarga, persistencia y despliegue.

## Componentes previstos

- Frontend: aplicación React/Vite separada para seleccionar perfiles, navegar y gestionar operaciones básicas de biblioteca, elegir destino, crear trabajos y consultar estados.
- Backend: API FastAPI con Pydantic v2. Actualmente incluye configuración base, `GET /api/v1/health`, `GET /api/v1/profiles`, navegación con `GET /api/v1/profiles/{profile_id}/entries`, creación de directorios con `POST /api/v1/profiles/{profile_id}/directories`, renombrado con `PATCH /api/v1/profiles/{profile_id}/entries/rename`, movimiento con `POST /api/v1/profiles/{profile_id}/entries/move`, envío a papelera con `DELETE /api/v1/profiles/{profile_id}/entries` y endpoints para crear y consultar trabajos de descarga.
- Worker de descargas: proceso independiente one-shot para reclamar un trabajo de MariaDB, descargar una pista de audio con `yt-dlp`, publicar el resultado en NFS y finalizar el estado.
- MariaDB: base de datos para trabajos de descarga, eventos, estados e historial. La capa ORM y las migraciones iniciales ya están preparadas.
- Almacenamiento NFS: ubicaciones compartidas por perfil para archivos descargados.
- Infraestructura: plantillas para Nginx central con HTTPS, Caddy HTTP interno en el CT y servicios systemd en `infra/`.

## Flujo web

```text
Navegador
  ↓
Frontend React/Vite
  ↓ /api/v1
FastAPI
  ↓
MariaDB / worker / NFS
```

En desarrollo, Vite usa un proxy para reenviar `/api` a `http://127.0.0.1:8080`. La API no configura CORS en esta fase. En producción se espera servir el frontend estático y la API bajo el mismo origen público mediante Nginx central y Caddy interno. Las plantillas de Nginx, Caddy y systemd están en `infra/`.

## Topología de despliegue prevista

```text
Cliente
  ↓ HTTPS 443
Nginx central
  ↓ HTTP interno TCP 8081
Caddy en CT
  ├── frontend React estático
  └── /api/* → FastAPI en 127.0.0.1:8080
                    ↓
                 MariaDB externa
                    ↑
worker systemd timer → staging local → NFS por perfil
```

FastAPI no queda accesible desde la red: escucha en `127.0.0.1:8080`. El DNS interno `music.alejandrogb.local` debe resolver al Nginx central. Nginx es el único componente que escucha en `443` para ese nombre, termina HTTPS y reenvía HTTP interno a `IP_CT:8081`. Caddy en el CT no usa certificados, escucha solo en la IP real del CT y sirve el build estático; reenvía únicamente `/api/*` conservando el prefijo `/api`.

El firewall del CT debe permitir TCP `8081` exclusivamente desde el Nginx central. Caddy debe confiar solo en la IP del Nginx central como proxy. Los certificados y claves pertenecen al Nginx central y no deben versionarse ni copiarse al repositorio.

No hay autenticación todavía. Antes de exponer el servicio fuera de una LAN de confianza harán falta autenticación, revisión de firewall, política TLS pública si procede y endurecimiento operativo adicional.

```text
Frontend Biblioteca
  ├── listar entradas
  ├── seleccionar destino de descarga
  ├── crear carpetas
  ├── renombrar entradas
  ├── mover dentro del perfil
  └── enviar a papelera
```

## Perfiles de biblioteca

Los perfiles se definen en un fichero JSON externo (`profiles.json`) indicado por la variable de entorno `PROFILES_CONFIG_PATH`. Su valor por defecto es `/etc/yt-downloader/profiles.json`.

Las exclusiones del navegador de biblioteca se definen en un fichero independiente indicado por `LIBRARY_EXCLUSIONS_CONFIG_PATH`, con valor de producción `/etc/yt-downloader/library-exclusions.json`. Si no existe, no se excluye ningún nombre; si existe y no es válido, las rutas de biblioteca devuelven un error seguro sin rutas internas.

Este fichero es configuración de infraestructura: contiene las rutas raíz reales de cada biblioteca y no debe exponerse al cliente. La API solo devuelve `id` y `display_name` de perfiles habilitados.

El ejemplo versionable vive en `config/profiles.example.json`. Para desarrollo local puede usarse así, sin modificar `/etc`:

```bash
PROFILES_CONFIG_PATH="$PWD/config/profiles.example.json" uv run --project backend uvicorn yt_downloader_api.main:app --host 127.0.0.1 --port 8080 --reload
```

## Navegación de bibliotecas

Cada perfil apunta a una raíz NFS independiente mediante `root_path`. `/mnt/music` puede ser solo un directorio padre local, no un montaje único compartido. Ejemplos de raíces de perfil: `/mnt/music/alejandrogb` y `/mnt/music/pepe`.

Cada montaje de perfil debe definirse en `/etc/fstab` con `_netdev`. Ejemplo orientativo:

```fstab
nas:/export/music/alejandrogb /mnt/music/alejandrogb nfs4 rw,_netdev,noatime 0 0
nas:/export/music/pepe /mnt/music/pepe nfs4 rw,_netdev,noatime 0 0
```

El worker valida la ruta concreta del perfil antes de ejecutar o publicar una descarga. Si falta un montaje NFS, el fallo afecta a ese perfil o trabajo, no a todos los perfiles.

La API de navegación usa siempre rutas relativas al `root_path` del perfil. El cliente nunca recibe rutas reales del sistema, rutas absolutas ni el valor de `root_path`.

Solo se listan ficheros y directorios normales; se ocultan elementos cuyo nombre empieza por `.` y enlaces simbólicos. Tampoco se permite navegar a través de enlaces simbólicos.

La creación de directorios está limitada estrictamente a la raíz del perfil configurado. La API valida rutas relativas y nombres de directorio antes de tocar el sistema de archivos, no usa comandos externos y no expone rutas absolutas.

El renombrado de ficheros y directorios se limita al mismo directorio padre. El campo `new_name` se trata únicamente como nombre de entrada, no como ruta, por lo que no permite mover elementos entre directorios.

El movimiento de ficheros y directorios se limita a la misma biblioteca del perfil. Conserva el nombre original y solo acepta como destino un directorio existente bajo la raíz configurada del perfil.

La eliminación actual no borra definitivamente. Mueve la entrada a `.trash` dentro de la raíz del perfil, usando un nombre interno único. La API no devuelve la ubicación interna en papelera y `.trash` no aparece en los listados normales porque las entradas ocultas no se exponen.

El sistema de archivos NFS será la fuente de verdad de las bibliotecas. Todavía no hay borrado definitivo, vaciado de papelera ni restauración.

## Persistencia y flujo futuro

La API FastAPI usa MariaDB para registrar trabajos de descarga y consultar sus eventos. El worker one-shot también usa MariaDB para tomar trabajos, actualizar progreso, registrar eventos y cerrar estados.

Flujo previsto:

```text
FastAPI -> MariaDB -> queued job
Worker -> MariaDB -> running
Worker -> staging local
Worker -> yt-dlp audio-only download
Worker -> destination NFS
Worker -> MariaDB -> completed / failed
```

MariaDB no sustituye a NFS. Los archivos descargados y las bibliotecas seguirán viviendo en el sistema de archivos montado; MariaDB almacenará trabajos, estados, eventos y metadatos operativos.

El esquema se gestiona con Alembic. No se crean tablas automáticamente al iniciar FastAPI.

Flujo actual para registrar un trabajo:

```text
Cliente -> FastAPI -> validación de perfil y destino NFS -> MariaDB
```

Flujo actual para consultar cola e historial:

```text
Cliente -> FastAPI -> MariaDB
                  ^
          consulta de cola e historial
```

La API solo registra el trabajo en cola. No ejecuta yt-dlp, FFmpeg ni procesos externos.

Flujo actual del worker one-shot:

```text
Worker -> MariaDB -> marca running obsoletos como failed
Worker -> MariaDB -> reclama como máximo un queued -> running
Worker -> staging local -> descarga audio con yt-dlp
Worker -> NFS -> publica fichero final sin sobrescribir
Worker -> MariaDB -> completed / failed
```

El worker actualiza `heartbeat_at` al reclamar el trabajo y durante la descarga. El fichero se descarga primero bajo `DOWNLOAD_STAGING_ROOT/<job_id>/` y no aparece en la biblioteca hasta que la descarga ha terminado y la copia al destino se ha completado. El temporal de publicación dentro de NFS es oculto y no aparece en el listado normal.

## Política de descarga

El worker descarga solo audio. La política inicial prioriza una pista M4A directa y, si no existe, conserva el mejor audio disponible sin recodificar.

Comportamiento previsto:

- Selecciona solo audio.
- Prioriza M4A.
- Conserva el formato fuente si no hay M4A.
- No recodifica por defecto.
- Registra el formato real obtenido.
- No configura postprocesadores de extracción o conversión.

La compatibilidad de formatos de fallback con Audio Station se comprobará más adelante. No hay conversión de compatibilidad en esta fase y `transcode_applied` permanece en `false`.

## Estado actual

La parte funcional actual incluye el backend en `backend`, ejecutable con Uvicorn en `127.0.0.1:8080`, el frontend React/Vite en `frontend`, ejecutable en desarrollo con `npm run dev`, y plantillas de despliegue sin Docker en `infra/`.

No hay Dockerfiles ni `docker-compose` en este bloque.
