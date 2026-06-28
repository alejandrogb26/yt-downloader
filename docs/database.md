# Base de Datos

MariaDB será la base de datos relacional del sistema para trabajos de descarga, eventos asociados, estados e historial operativo.

## Responsabilidades

- `profiles.json`: define perfiles de biblioteca y sus rutas raíz. Es configuración de infraestructura.
- NFS: contiene las bibliotecas y los archivos reales. Es la fuente de verdad del contenido.
- MariaDB: almacena trabajos de descarga, eventos, progreso, errores y metadatos operativos.

MariaDB no sustituye al sistema de archivos ni almacena los archivos descargados.

## Tablas Iniciales

`download_jobs` almacena un trabajo de descarga:

- `id`: UUID textual del trabajo.
- `profile_id`: perfil de biblioteca definido en `profiles.json`, sin foreign key.
- `source_url`: URL origen.
- `destination_relative_path`: destino relativo dentro del perfil.
- `requested_format`: formato solicitado, inicialmente `mp3`.
- `requested_audio_quality`: calidad solicitada opcional.
- `status`: estado textual del trabajo.
- `progress_percent`: progreso opcional.
- `title`: título detectado opcional.
- `output_relative_path`: salida final relativa opcional.
- `error_code` y `error_message`: error opcional.
- `worker_id`: worker que procesa el trabajo.
- `attempt_count`: número de intentos.
- `created_at`, `updated_at`, `started_at`, `finished_at`: fechas UTC.

Estados iniciales:

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`

`download_job_events` almacena eventos relevantes de cada trabajo:

- `id`: identificador autoincremental.
- `job_id`: foreign key a `download_jobs.id` con borrado en cascada.
- `created_at`: fecha UTC del evento.
- `level`: nivel del evento.
- `message`: mensaje resumido.
- `progress_percent`: progreso opcional.

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
