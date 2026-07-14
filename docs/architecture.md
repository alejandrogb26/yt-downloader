# Arquitectura

`yt-downloader` se plantea como un monorepo con componentes separados para interfaz web, API, procesos de descarga, persistencia y despliegue.

## Componentes previstos

- Frontend: aplicación React/Vite separada para seleccionar perfiles, navegar y gestionar operaciones básicas de biblioteca, elegir destino, crear trabajos y consultar estados.
- Backend: API FastAPI con Pydantic v2. Actualmente incluye autenticación con cookie HttpOnly, `GET /api/v1/health`, `GET /api/v1/profiles`, navegación con `GET /api/v1/profiles/{profile_id}/entries`, creación de directorios con `POST /api/v1/profiles/{profile_id}/directories`, renombrado con `PATCH /api/v1/profiles/{profile_id}/entries/rename`, movimiento con `POST /api/v1/profiles/{profile_id}/entries/move`, envío a papelera con `DELETE /api/v1/profiles/{profile_id}/entries`, operaciones de audio sin recodificación bajo `/api/v1/profiles/{profile_id}/audio/*` y endpoints para crear y consultar trabajos de descarga.
- Worker de descargas: proceso independiente persistente y concurrente para reclamar trabajos de MariaDB, descargar pistas de audio con `yt-dlp`, publicar resultados en NFS y finalizar estados. Conserva `--once` solo como modo manual o de diagnóstico.
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
  ├── /api/* → FastAPI en 127.0.0.1:8080
  └── /docs, /redoc, /openapi.json → FastAPI en 127.0.0.1:8080
                    ↓
                 MariaDB externa
                    ↑
worker systemd persistente → staging local → NFS por perfil
```

FastAPI no queda accesible desde la red: escucha en `127.0.0.1:8080`. El DNS interno `music.alejandrogb.local` debe resolver al Nginx central. Nginx es el único componente que escucha en `443` para ese nombre, termina HTTPS y reenvía HTTP interno a `IP_CT:8081`. Caddy en el CT no usa certificados, escucha solo en la IP real del CT y sirve el build estático; reenvía `/api/*` conservando el prefijo `/api`.

Caddy también publica las rutas de documentación automáticas de FastAPI bajo el hostname principal: Swagger UI en `/docs`, ReDoc en `/redoc` y OpenAPI JSON en `/openapi.json`. Estas rutas pasan por el mismo proxy normal de la aplicación hacia `127.0.0.1:8080`, antes del fallback SPA, sin abrir puertos nuevos y sin reescribir prefijos.

El firewall del CT debe permitir TCP `8081` exclusivamente desde el Nginx central. Caddy debe confiar solo en la IP del Nginx central como proxy. Los certificados y claves pertenecen al Nginx central y no deben versionarse ni copiarse al repositorio.

Hay autenticación con sesiones por cookie HttpOnly y CSRF para mutaciones. Antes de exponer el servicio fuera de una LAN de confianza harán falta revisión de firewall, política TLS pública si procede y endurecimiento operativo adicional.

```text
Frontend Biblioteca
  ├── listar entradas
  ├── seleccionar destino de descarga
  ├── crear carpetas
  ├── renombrar entradas
  ├── mover dentro del perfil
  ├── enviar a papelera
  └── recortar o editar metadatos de .m4a sin recodificar
```

## Perfiles de biblioteca

Los perfiles runtime se definen en MariaDB en `library_profiles`. El antiguo `profiles.json` queda reservado para importación inicial mediante CLI administrativa.

Las exclusiones del navegador de biblioteca se definen en un fichero independiente indicado por `LIBRARY_EXCLUSIONS_CONFIG_PATH`, con valor de producción `/etc/yt-downloader/library-exclusions.json`. Si no existe, no se excluye ningún nombre; si existe y no es válido, las rutas de biblioteca devuelven un error seguro sin rutas internas.

`library_profiles.root_path` contiene las rutas raíz reales de cada biblioteca y no debe exponerse al cliente. La API solo devuelve `id` y `display_name` de perfiles habilitados autorizados para el usuario.

El ejemplo versionable vive en `config/profiles.example.json`. Para desarrollo local puede usarse así, sin modificar `/etc`:

El ejemplo versionable `config/profiles.example.json` puede importarse con `python -m yt_downloader_api.admin.import_profiles --profiles-json config/profiles.example.json` en un entorno local con `DATABASE_URL` configurada.

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

## Operaciones de audio

La Biblioteca permite operar sobre archivos `.m4a` existentes dentro de perfiles autorizados. Estas operaciones no pasan por la cola del worker, no crean trabajos de descarga y no cambian la política de `yt-dlp`.

El recorte usa `ffmpeg` con `-c:a copy`; la edición de metadatos usa `ffmpeg` con `-c copy`. No se configuran codecs de salida como `aac`, `libmp3lame` u `opus`, por lo que no hay recodificación, conversión a MP3, cambio de bitrate, normalización, fades ni mezcla. El recorte sin recodificación puede quedar ajustado a límites de frame o paquete y no promete exactitud al milisegundo.

Las rutas `FFMPEG_PATH` y `FFPROBE_PATH` permiten fijar los binarios. Por defecto se ejecutan `ffmpeg` y `ffprobe` desde el `PATH` del proceso. Si no están disponibles o fallan, la API devuelve errores públicos en español sin stderr, trazas ni rutas internas.

Las operaciones reutilizan la validación de rutas de Biblioteca: usuario autenticado, acceso al perfil, rutas relativas, sin `..`, sin componentes ocultos, sin symlinks y respetando exclusiones. Las mutaciones requieren CSRF. Las escrituras se hacen en temporales ocultos dentro de la misma carpeta NFS y solo se publican si `ffmpeg` termina correctamente y el resultado no está vacío.

## Persistencia y flujo futuro

La API FastAPI usa MariaDB para usuarios, sesiones, perfiles, permisos, trabajos de descarga y eventos. El worker persistente también usa MariaDB para tomar trabajos, cargar perfiles, actualizar progreso, mantener heartbeat, registrar eventos y cerrar estados.

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

La API solo registra el trabajo en cola. No ejecuta yt-dlp para descargas ni usa el worker para operaciones de audio. Las operaciones manuales de Biblioteca sí pueden ejecutar `ffmpeg`/`ffprobe` de forma síncrona para copia de streams sin recodificación.

Flujo actual del worker persistente:

```text
Worker -> MariaDB -> marca running obsoletos como failed
Worker -> MariaDB -> reclama queued hasta WORKER_CONCURRENCY -> running
Worker -> heartbeat autónomo por trabajo activo
Worker -> staging local -> descarga audio con yt-dlp y reintentos controlados
Worker -> NFS -> publica fichero final sin sobrescribir
Worker -> MariaDB -> completed / failed
```

El worker persistente reclama trabajos de la cola y ejecuta hasta `WORKER_CONCURRENCY` descargas en paralelo. Cada trabajo usa instancia de `yt-dlp`, staging `DOWNLOAD_STAGING_ROOT/<job_id>/` y sesiones SQLAlchemy aisladas. `WORKER_QUEUE_POLL_INTERVAL_SECONDS` controla el sondeo cuando no hay trabajo o capacidad. `WORKER_HEARTBEAT_INTERVAL_SECONDS` controla un heartbeat autónomo por trabajo activo y debe ser menor que `WORKER_STALE_JOB_TIMEOUT_SECONDS`. El heartbeat no depende de eventos ni de hooks de progreso, por lo que sigue activo durante pausas de descarga, backoff de reintento, copia a NFS y resolución de colisiones. Si un worker cae, los trabajos obsoletos se recuperan por timeout. El fichero no aparece en la biblioteca hasta que la descarga ha terminado y la copia al destino se ha completado. El temporal de publicación dentro de NFS es oculto y no aparece en el listado normal.

La fase de descarga/resolución de yt-dlp se reintenta dentro del mismo trabajo cuando el adaptador de descarga devuelve un error. `YT_DLP_MAX_ATTEMPTS` vale `3` por defecto e incluye el intento inicial; `YT_DLP_RETRY_INITIAL_DELAY_SECONDS` vale `2` y se duplica en cada reintento, por lo que los retrasos por defecto son 2 y 4 segundos. Antes de reintentar se limpia el staging parcial del intento fallido y el siguiente intento crea una nueva instancia de `YoutubeDL`. No se reintentan errores de validación local, perfiles, rutas, staging, publicación NFS, MariaDB ni errores internos ajenos a yt-dlp. La publicación NFS se ejecuta solo una vez, después de una descarga exitosa. Si algunos vídeos de un lote agotan sus intentos, esos trabajos quedan `failed` y el lote puede calcularse como `completed_with_errors`.

Ante SIGTERM, el worker deja de reclamar trabajos nuevos, pero espera a que los trabajos activos terminen. Durante esa espera ordenada los heartbeats autónomos continúan para evitar que otro ciclo de recuperación marque esos trabajos como obsoletos.

Las descargas por lote crean una fila en `download_batches` y trabajos normales relacionados por `batch_id`. Los estados y contadores del lote se calculan a partir de sus trabajos para evitar desincronización.

## Health checks

`GET /api/v1/health` es liveness: responde si el proceso FastAPI está vivo y no depende de MariaDB, NFS ni YouTube.

`GET /api/v1/health/ready` es readiness: realiza una consulta ligera `SELECT 1` contra MariaDB, comprueba que existan las tablas de autenticación/perfiles/sesiones y valida la configuración de exclusiones de biblioteca. No recorre montajes NFS, no lista bibliotecas, no ejecuta migraciones y no expone rutas absolutas ni secretos. Devuelve `200` con `status=ready` si todo está disponible y `503` con checks públicos si alguna dependencia no está lista.

## Búsqueda de biblioteca

La búsqueda global de biblioteca recorre entradas visibles del perfil en un orden estable. Cuando se solicita `limit`, devuelve como máximo ese número de resultados. Si encuentra una coincidencia adicional, devuelve `truncated=true` y detiene el recorrido sin visitar directorios pendientes. En resultados truncados se prioriza evitar I/O NFS innecesario sobre calcular una ordenación global completa de todo el árbol.

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

El backend depende de `yt-dlp[default]`, que incluye componentes recomendados como `yt-dlp-ejs`. Para las firmas y requisitos actuales de YouTube, el entorno de ejecución debe proporcionar un runtime JavaScript externo compatible. En despliegue se usa Deno como dependencia del sistema, instalado en una ruta global como `/usr/local/bin/deno` y disponible en el `PATH` del worker systemd. La aplicación no fija una ruta de Deno ni modifica opciones de `YoutubeDL`: yt-dlp detecta el runtime automáticamente desde el entorno del proceso.

## Estado actual

La parte funcional actual incluye el backend en `backend`, ejecutable con Uvicorn en `127.0.0.1:8080`, el frontend React/Vite en `frontend`, ejecutable en desarrollo con `npm run dev`, y plantillas de despliegue sin Docker en `infra/`.

No hay Dockerfiles ni `docker-compose` en este bloque.
