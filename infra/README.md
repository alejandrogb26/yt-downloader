# Despliegue en CT LXC sin Docker

Este directorio contiene plantillas para desplegar `yt-downloader` en un CT LXC de Proxmox con Debian 13 y sin Docker. No instala paquetes ni habilita servicios por sí mismo.

## Topología

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
worker systemd persistente → staging local → NFS por perfil
```

El DNS interno `music.alejandrogb.local` debe resolver al Nginx central, no al CT. Nginx es el único componente que escucha en `443` para ese nombre, termina HTTPS con el certificado gestionado por el administrador y reenvía HTTP interno al CT en TCP `8081`.

Caddy en el CT no usa certificados ni claves privadas. FastAPI escucha solo en `127.0.0.1:8080`. El firewall del CT debe permitir TCP `8081` únicamente desde `IP_NGINX`.

No hay autenticación todavía. Limita este servicio a una LAN de confianza mediante firewall y no expongas `443` a Internet.

## Rutas

- Repositorio: `/opt/yt-downloader`
- Backend: `/opt/yt-downloader/backend`
- Entorno virtual backend: `/opt/yt-downloader/backend/.venv`
- Frontend compilado: `/var/www/yt-downloader`
- Configuración privada: `/etc/yt-downloader`
- Perfiles iniciales a importar: `/etc/yt-downloader/profiles.json`
- Exclusiones de biblioteca: `/etc/yt-downloader/library-exclusions.json`
- Variables de entorno: `/etc/yt-downloader/yt-downloader.env`
- Staging local: `/var/lib/yt-downloader/staging`
- Bibliotecas NFS por perfil: `/mnt/music/alejandrogb`, `/mnt/music/pepe`, `/mnt/music/<otro-perfil>`

Los perfiles definen sus rutas individuales dentro de `/mnt/music`. Ese directorio puede ser solo el padre local; no debe asumirse que sea un punto de montaje único.

## Usuario de Servicio

Crea un usuario y grupo de sistema `yt-downloader`, sin fijar UID ni GID concretos. La API y el worker deben ejecutarse como `yt-downloader`, nunca como `root`.

Permisos esperados:

- `yt-downloader` puede leer `/opt/yt-downloader`.
- `yt-downloader` puede leer `/etc/yt-downloader/profiles.json`.
- `yt-downloader` puede leer `/etc/yt-downloader/yt-downloader.env`.
- `yt-downloader` puede escribir en `/var/lib/yt-downloader/staging`.
- `yt-downloader` tiene permisos NFS reales sobre las rutas configuradas para perfiles.
- `caddy` solo necesita lectura de `/var/www/yt-downloader`.

Los certificados y claves privadas se gestionan en el Nginx central. No deben copiarse al CT ni versionarse en este repositorio.

## Entorno

Plantilla: `infra/env/yt-downloader.env.example`.

El fichero real recomendado es `/etc/yt-downloader/yt-downloader.env`, propietario `root`, grupo `yt-downloader`, modo `0640`. Es formato `KEY=value`, no un script de shell. No lo expongas al frontend y no imprimas nunca `DATABASE_URL`.

Ejemplo de instalación de ficheros privados:

```bash
sudo install -d -m 0750 -o root -g yt-downloader /etc/yt-downloader
sudo install -d -m 0750 -o yt-downloader -g yt-downloader /var/lib/yt-downloader/staging
sudo install -m 0640 -o root -g yt-downloader /ruta/al/yt-downloader.env /etc/yt-downloader/yt-downloader.env
sudo install -m 0640 -o root -g yt-downloader /ruta/a/profiles.json /etc/yt-downloader/profiles.json
sudo install -m 0640 -o root -g yt-downloader infra/config/library-exclusions.json.example /etc/yt-downloader/library-exclusions.json
```

`profiles.json` ya no es fuente runtime. Úsalo solo para importación inicial a MariaDB. `LIBRARY_EXCLUSIONS_CONFIG_PATH` apunta al JSON de exclusiones de navegador. El formato es `{"excluded_names":["@eaDir"]}`. Los nombres son nombres base exactos, sin rutas ni patrones; si el fichero no existe, la API usa una lista vacía.

## Backend

Verifica la ruta de `uv` antes de instalar dependencias. Verifica también que Python del entorno virtual sea 3.14.

El paquete Python se bloquea con `yt-dlp[default]`, que incluye dependencias recomendadas como `yt-dlp-ejs`. Para YouTube, el CT debe proporcionar además un runtime JavaScript externo compatible. Instala Deno de forma global, por ejemplo en `/usr/local/bin/deno`, y asegúrate de que el usuario de servicio `yt-downloader` puede ejecutarlo. No lo instales en el home de `root` ni dependas de rutas privadas de usuario.

Instalar dependencias bloqueadas:

```bash
sudo -u yt-downloader /usr/local/bin/uv sync --frozen --project /opt/yt-downloader/backend
```

Aplicar migraciones:

```bash
cd /opt/yt-downloader
set -a
. /etc/yt-downloader/yt-downloader.env
set +a
sudo -u yt-downloader /usr/local/bin/uv run --frozen --no-sync --project backend alembic -c backend/alembic.ini upgrade head
```

Bootstrap inicial de autenticación y perfiles después de migrar:

```bash
sudo -u yt-downloader /opt/yt-downloader/backend/.venv/bin/python -m yt_downloader_api.admin.import_profiles --profiles-json /etc/yt-downloader/profiles.json
sudo -u yt-downloader /opt/yt-downloader/backend/.venv/bin/python -m yt_downloader_api.admin.create_user --username admin --display-name Admin --admin --password
sudo -u yt-downloader /opt/yt-downloader/backend/.venv/bin/python -m yt_downloader_api.admin.grant_profile --username admin --profile alejandrogb --role owner
```

Repite `grant_profile` para cada biblioteca necesaria. Las sesiones usan cookie `HttpOnly`; en producción `SESSION_COOKIE_SECURE=true` requiere acceso por HTTPS a través del Nginx central. Si haces una prueba directa por HTTP contra Caddy, la cookie segura no se enviará.

Los servicios systemd no usan `uv run` en ejecución normal. Usan directamente los binarios ya instalados en `/opt/yt-downloader/backend/.venv`.

`yt-dlp` detecta Deno automáticamente si `deno` está disponible en el `PATH` del proceso systemd. La unidad del worker fija un `PATH` explícito que incluye rutas globales como `/usr/local/bin`, por lo que Deno debe instalarse en una ruta global incluida ahí, por ejemplo `/usr/local/bin/deno`. No hay una variable de entorno de la aplicación para fijar la ruta del runtime JavaScript y no debe hardcodearse una ruta específica del CT en el repositorio.

La fase de resolución/descarga con yt-dlp usa reintentos internos controlados por `YT_DLP_MAX_ATTEMPTS=3` y `YT_DLP_RETRY_INITIAL_DELAY_SECONDS=2`. El máximo incluye el intento inicial; con esos valores espera 2 segundos antes del segundo intento y 4 antes del tercero. Solo cubre errores reportados por el adaptador de yt-dlp; no reintenta validaciones locales, staging, publicación NFS, MariaDB ni errores internos ajenos a yt-dlp. Si algunos trabajos de un lote agotan sus intentos, el lote puede quedar como `completed_with_errors`.

Después de instalar Deno en el CT, verifica como usuario de servicio:

```bash
runuser -u yt-downloader -- deno --version
runuser -u yt-downloader -- /opt/yt-downloader/backend/.venv/bin/python -m yt_dlp --verbose --simulate 'https://www.youtube.com/watch?v=VIDEO_ID'
```

La salida verbose de `yt-dlp` debe mostrar que encuentra un runtime JavaScript compatible y no debe mostrar `No supported JavaScript runtime could be found`.

## Frontend

Construir el frontend:

```bash
cd /opt/yt-downloader/frontend
npm ci
npm run build
```

Copia el contenido de `/opt/yt-downloader/frontend/dist` a `/var/www/yt-downloader`. No uses `vite dev`, `vite preview` ni un servidor Node en producción.

Para una copia reversible, conserva el build anterior antes de reemplazarlo:

```bash
sudo install -d -m 0755 -o root -g root /var/www/yt-downloader
sudo cp -a /var/www/yt-downloader /var/www/yt-downloader.previous
sudo rsync -a --delete /opt/yt-downloader/frontend/dist/ /var/www/yt-downloader/
sudo chown -R root:root /var/www/yt-downloader
sudo chmod -R a+rX /var/www/yt-downloader
```

El usuario `caddy` debe poder leer `/var/www/yt-downloader`.

## Caddy

Plantilla: `infra/caddy/Caddyfile.internal.example`.

La configuración escucha en HTTP interno `IP_CT:8081`, enlazada solo a `IP_CT`. Sirve `/var/www/yt-downloader`, soporta rutas SPA con fallback a `/index.html`, y reenvía `/api/*` a `127.0.0.1:8080` sin reescribir la ruta.

También publica la documentación automática de FastAPI a través del mismo proxy normal de la aplicación, sin abrir puertos nuevos ni cambiar FastAPI: Swagger UI en `/docs`, ReDoc en `/redoc` y el esquema OpenAPI en `/openapi.json`. Estas rutas se envían a `127.0.0.1:8080` antes del fallback estático del frontend y conservan su ruta original.

Sustituye `IP_CT` por la IP real del CT y `IP_NGINX` por la IP real del Nginx central. Caddy debe confiar únicamente en `IP_NGINX/32` como proxy. El firewall del CT debe permitir TCP `8081` exclusivamente desde `IP_NGINX`.

Instalar y validar:

```bash
sudo install -m 0644 infra/caddy/Caddyfile.internal.example /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl enable --now caddy
```

## Nginx central

Plantilla: `infra/nginx/music.alejandrogb.local.conf.example`.

Nginx recibe HTTPS en `443` para `music.alejandrogb.local`, termina TLS con el certificado gestionado por el administrador y reenvía HTTP interno a `http://IP_CT:8081`. Sustituye `IP_CT` por la IP real del CT. No añadas una URI al `proxy_pass`, para no alterar rutas ni quitar el prefijo `/api`.

Tras cambiar la configuración del virtual host o renovar el certificado en el servidor Nginx, valida y recarga Nginx según el procedimiento operativo de ese servidor.

## NFS por perfil

Cada perfil tiene una raíz NFS independiente definida en `/etc/yt-downloader/profiles.json`. Ejemplo orientativo:

```json
{
  "profiles": [
    {
      "id": "alejandrogb",
      "display_name": "Alejandro GB",
      "root_path": "/mnt/music/alejandrogb",
      "enabled": true
    },
    {
      "id": "pepe",
      "display_name": "Pepe",
      "root_path": "/mnt/music/pepe",
      "enabled": true
    }
  ]
}
```

Cada montaje de perfil debe estar definido en `/etc/fstab` con `_netdev`. Ejemplo orientativo:

```fstab
nas:/export/music/alejandrogb /mnt/music/alejandrogb nfs4 rw,_netdev,noatime 0 0
nas:/export/music/pepe /mnt/music/pepe nfs4 rw,_netdev,noatime 0 0
```

El worker valida la ruta concreta del perfil antes de ejecutar o publicar una descarga. Un montaje NFS ausente afecta solo a ese perfil o trabajo.

## systemd

Instalar unidades:

```bash
sudo install -m 0644 infra/systemd/yt-downloader-api.service /etc/systemd/system/
sudo install -m 0644 infra/systemd/yt-downloader-worker.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now yt-downloader-api.service
sudo systemctl enable --now yt-downloader-worker.service
```

El worker es un servicio persistente y concurrente. Reclama trabajos hasta `WORKER_CONCURRENCY` y sondea la cola cada `WORKER_QUEUE_POLL_INTERVAL_SECONDS` cuando no hay capacidad o trabajo pendiente. Cada trabajo activo mantiene `heartbeat_at` cada `WORKER_HEARTBEAT_INTERVAL_SECONDS`; ese valor debe ser positivo y menor que `WORKER_STALE_JOB_TIMEOUT_SECONDS`, que se usa para recuperar trabajos `running` abandonados.

Un trabajo esperando el backoff de yt-dlp sigue contando como activo, ocupa su slot de concurrencia y mantiene heartbeat. Si systemd solicita parada durante esa espera, el worker no inicia otro intento de yt-dlp para ese trabajo.

`--once` queda reservado para ejecución manual o diagnóstico: procesa como máximo un trabajo y sale. No es el mecanismo operativo de producción.

Ante `SIGTERM`, el worker deja de reclamar trabajos nuevos y espera a que finalicen los activos. Durante esa parada ordenada los heartbeats de trabajos activos continúan. La unidad `yt-downloader-worker.service` usa `TimeoutStopSec=1h`; si se supera, systemd puede terminar el proceso de forma forzada y la recuperación stale actuará en el siguiente arranque.

Si existe una instalación antigua con timer one-shot, deshabilita el timer y usa el servicio persistente:

```bash
sudo systemctl disable --now yt-downloader-worker.timer
sudo systemctl daemon-reload
sudo systemctl enable --now yt-downloader-worker.service
```

## Comprobación

```bash
systemctl status caddy
systemctl status yt-downloader-api.service
systemctl status yt-downloader-worker.service
journalctl -u yt-downloader-api.service -f
journalctl -u yt-downloader-worker.service -f
curl https://music.alejandrogb.local/api/v1/health
curl https://music.alejandrogb.local/api/v1/health/ready
curl -H 'Host: music.alejandrogb.local' http://IP_CT:8081/api/v1/health
curl -H 'Host: music.alejandrogb.local' http://IP_CT:8081/api/v1/health/ready
findmnt -T /mnt/music/alejandrogb
findmnt -T /mnt/music/pepe
```

`/api/v1/health` es liveness y solo confirma que FastAPI responde. `/api/v1/health/ready` comprueba MariaDB, tablas de autenticación/perfiles/sesiones y configuración de exclusiones sin recorrer NFS. Los primeros `curl` se ejecutan desde un cliente LAN y pasan por Nginx central. Los `curl` con `Host` se ejecutan desde el CT para comprobar Caddy directamente sin depender del DNS público interno. Los comandos `findmnt` verifican montajes concretos de perfiles.

Rollback seguro de esta fase: restaura el despliegue anterior de backend/frontend y detén API/worker antes de degradar esquema. No borres `profiles.json`; puede volver a importarse. Las cookies de sesión quedan invalidadas si se revierte a una versión sin autenticación.

## Rollback

1. Si existe un timer antiguo, deshabilítalo: `sudo systemctl disable --now yt-downloader-worker.timer`.
2. Detén worker y API: `sudo systemctl stop yt-downloader-worker.service yt-downloader-api.service`.
3. Restaura el frontend anterior desde `/var/www/yt-downloader.previous`.
4. Restaura copias anteriores de `/etc/yt-downloader`.
5. Valida Caddy antes de recargar: `sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`.
6. Recarga o reinicia servicios solo después de validar configuración.

## Notas Operativas

`yt-dlp-ejs` forma parte de las dependencias Python bloqueadas mediante `yt-dlp[default]`. Deno sigue siendo una dependencia del sistema y debe instalarse fuera del entorno virtual, en una ruta global accesible por `yt-downloader`.
