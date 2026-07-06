# Base de Datos

MariaDB será la base de datos relacional del sistema para la cola de trabajos de descarga, eventos asociados, estados e historial operativo.

## Responsabilidades

- `profiles.json`: define perfiles de biblioteca y sus rutas raíz. Es configuración de infraestructura.
- NFS: contiene las bibliotecas y los archivos reales. Es la fuente de verdad del contenido.
- MariaDB: almacena trabajos de descarga, eventos, progreso, errores y metadatos operativos.

MariaDB no sustituye al sistema de archivos ni almacena los archivos descargados.

Cada trabajo creado en estado `queued` genera también un evento inicial en `download_job_events` con el mensaje `Download job queued.`. La creación del trabajo y del evento debe ser atómica.

## Tablas Iniciales

`download_jobs` almacena la cola y el historial de trabajos de descarga:

- `id`: UUID textual del trabajo.
- `profile_id`: perfil de biblioteca definido en `profiles.json`, sin foreign key.
- `source_url`: URL origen.
- `destination_relative_path`: destino relativo dentro del perfil.
- `audio_policy`: política de audio solicitada, inicialmente `prefer_m4a_then_best_source`.
- `status`: estado textual del trabajo.
- `progress_percent`: progreso opcional.
- `title`: título detectado opcional.
- `output_relative_path`: salida final relativa opcional.
- `source_format_id`: formato real seleccionado por `yt-dlp`.
- `source_container`: contenedor de la fuente seleccionada por `yt-dlp`.
- `source_audio_codec`: códec de audio de la fuente seleccionada por `yt-dlp`.
- `output_container`: contenedor real del archivo final publicado en la biblioteca.
- `output_audio_codec`: códec de audio real del archivo final publicado en la biblioteca.
- `transcode_applied`: indica si se aplicó transcodificación. En esta primera versión será siempre `false`.
- `error_code` y `error_message`: error opcional.
- `worker_id`: worker que procesa el trabajo.
- `attempt_count`: número de intentos.
- `heartbeat_at`: última señal UTC del worker que tiene reclamado el trabajo.
- `created_at`, `updated_at`, `started_at`, `finished_at`: fechas UTC.

Estados del trabajo:

- `queued`: creado por la API y pendiente de que un worker lo reclame.
- `running`: reclamado por un worker y en descarga o publicación.
- `completed`: descarga publicada correctamente en la biblioteca.
- `failed`: terminó con error o fue recuperado como obsoleto.
- `cancelled`: reservado para cancelaciones futuras.

El worker reclama trabajos `queued` mediante MariaDB y los pasa a `running` con `worker_id`, `started_at` y `heartbeat_at`. Durante la descarga actualiza `progress_percent` de forma limitada para evitar escrituras excesivas y mantiene `heartbeat_at` con un mecanismo autónomo independiente del progreso. Si detecta trabajos `running` con `heartbeat_at` anterior al umbral configurado los marca como `failed` con `error_code = worker_interrupted`.

El índice `(status, heartbeat_at)` acelera la búsqueda de trabajos `running` obsoletos. El índice `(status, created_at)` se usa para reclamar trabajos `queued` en orden de creación.

## Política de Audio

La primera versión descargará solo audio. No descargará vídeo y no debe convertir por defecto a MP3, FLAC ni ningún otro formato.

La política inicial es:

```text
prefer_m4a_then_best_source
```

La selección de `yt-dlp` es fija y equivalente a:

```text
bestaudio[ext=m4a]/bestaudio
```

M4A es una preferencia de descarga directa, no una conversión forzada. Si existe M4A, el resultado esperado normalmente será M4A/AAC. Si no existe, se conservará el mejor audio disponible, por ejemplo WebM/Opus.

Los campos `source_*` registran la fuente real seleccionada por `yt-dlp`. Los campos `output_*` registran el archivo final publicado. Como no hay conversión en esta versión, normalmente coinciden con `source_*`, pero se almacenan separados para una futura fase de postprocesado. `transcode_applied` queda preparado para una posible conversión de compatibilidad futura, pero en esta versión será siempre `false`.

`download_job_events` almacena eventos relevantes de cada trabajo:

- `id`: identificador autoincremental.
- `job_id`: foreign key a `download_jobs.id` con borrado en cascada.
- `created_at`: fecha UTC del evento.
- `level`: nivel del evento.
- `message`: mensaje resumido.
- `progress_percent`: progreso opcional.

Los listados de trabajos consultan historial persistido y no dependen de que el perfil siga existiendo o esté habilitado actualmente en `profiles.json`.

Eventos principales de descarga:

- `Download job queued.`: creado junto al trabajo inicial.
- `Download job claimed by worker.`: creado al reclamar el trabajo.
- `Download started.`: creado justo antes de ejecutar la descarga.
- `Audio download finished. Moving file to library.`: creado antes de publicar el archivo en NFS.
- `Download completed.`: creado en la misma transacción que marca el trabajo como `completed`, con `progress_percent = 100`.

Las actualizaciones de porcentaje no crean eventos para evitar spam en `download_job_events`. Los errores controlados crean un evento `error` con un mensaje público genérico y seguro, sin stack traces, rutas absolutas ni credenciales.

## DATABASE_URL

Formato esperado:

```text
mysql+pymysql://USER:PASSWORD@HOST:3306/DATABASE?charset=utf8mb4
```

No se debe imprimir ni registrar la URL completa porque contiene credenciales.

## Creación Manual de Base y Usuario

Ejemplo genérico para una instalación futura. Sustituye los valores por los reales de tu entorno y usa una contraseña segura:

```sql
CREATE DATABASE database_name CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'user_name'@'host_name' IDENTIFIED BY 'strong_password';
GRANT ALL PRIVILEGES ON database_name.* TO 'user_name'@'host_name';
FLUSH PRIVILEGES;
```

Usa siempre `utf8mb4`.

## Alembic

El esquema se aplica mediante Alembic, no al arrancar la API.

Comandos desde la raíz del repositorio:

```bash
uv run --project backend alembic -c backend/alembic.ini current
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend alembic -c backend/alembic.ini history
```

`current` y `upgrade head` requieren `DATABASE_URL` configurada. Si falta, Alembic muestra un error seguro indicando que la variable es obligatoria.

## Seguridad

No versiones `.env` ni credenciales. Usa `.env.example` solo como plantilla con valores no reales.
