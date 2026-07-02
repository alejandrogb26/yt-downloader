# Despliegue en CT LXC sin Docker

Este directorio contiene plantillas para desplegar `yt-downloader` en un CT LXC de Proxmox sin Docker. No instala paquetes ni habilita servicios por sí mismo.

## Topología

```text
Navegador
  ↓ HTTPS 443
Caddy
  ├── frontend React estático
  └── /api/* → FastAPI en 127.0.0.1:8080
                    ↓
                 MariaDB externa
                    ↑
systemd timer → worker one-shot → staging local → NFS
```

FastAPI escucha solo en `127.0.0.1:8080`. Caddy es el único servicio previsto escuchando en `443`. La configuración usa `tls internal`, por lo que los clientes deben confiar en la CA interna de Caddy para evitar advertencias HTTPS.

No hay autenticación todavía. Limita este servicio a una LAN de confianza mediante firewall y no expongas `443` a Internet.

## Rutas

- Repositorio: `/opt/yt-downloader`
- Backend: `/opt/yt-downloader/backend`
- Entorno virtual backend: `/opt/yt-downloader/backend/.venv`
- Frontend compilado: `/var/www/yt-downloader`
- Configuración privada: `/etc/yt-downloader`
- Perfiles: `/etc/yt-downloader/profiles.json`
- Variables de entorno: `/etc/yt-downloader/yt-downloader.env`
- Staging local: `/var/lib/yt-downloader/staging`
- Bibliotecas NFS: `/mnt/music`

Los perfiles definen sus rutas individuales dentro de `/mnt/music`.

## Usuario de Servicio

Crea un usuario y grupo de sistema `yt-downloader`, sin fijar UID ni GID concretos. La API y el worker deben ejecutarse como `yt-downloader`, nunca como `root`.

Permisos esperados:

- `yt-downloader` puede leer `/opt/yt-downloader`.
- `yt-downloader` puede leer `/etc/yt-downloader/profiles.json`.
- `yt-downloader` puede leer `/etc/yt-downloader/yt-downloader.env`.
- `yt-downloader` puede escribir en `/var/lib/yt-downloader/staging`.
- `yt-downloader` tiene permisos NFS reales sobre las rutas configuradas para perfiles.
- `caddy` solo necesita lectura de `/var/www/yt-downloader`.

## Entorno

Plantilla: `infra/env/yt-downloader.env.example`.

El fichero real recomendado es `/etc/yt-downloader/yt-downloader.env`, propietario `root`, grupo `yt-downloader`, modo `0640`. Es formato `KEY=value`, no un script de shell. No lo expongas al frontend y no imprimas nunca `DATABASE_URL`.

Ejemplo de instalación de ficheros privados:

```bash
sudo install -d -m 0750 -o root -g yt-downloader /etc/yt-downloader
sudo install -d -m 0750 -o yt-downloader -g yt-downloader /var/lib/yt-downloader/staging
sudo install -m 0640 -o root -g yt-downloader /ruta/al/yt-downloader.env /etc/yt-downloader/yt-downloader.env
sudo install -m 0640 -o root -g yt-downloader /ruta/a/profiles.json /etc/yt-downloader/profiles.json
```

## Backend

Verifica la ruta de `uv` antes de instalar dependencias. Verifica también que Python del entorno virtual sea 3.14.

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

Los servicios systemd no usan `uv run` en ejecución normal. Usan directamente los binarios ya instalados en `/opt/yt-downloader/backend/.venv`.

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

La configuración sirve `/var/www/yt-downloader`, soporta rutas SPA con fallback a `/index.html`, y reenvía solo `/api/*` a `127.0.0.1:8080`. Conserva el prefijo `/api` porque usa `handle`, no `handle_path`. No expone `/docs` ni `/openapi.json` salvo que existan bajo `/api/*`.

Instalar y validar:

```bash
sudo install -m 0644 infra/caddy/Caddyfile.internal.example /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl enable --now caddy
```

Esta configuración es para red interna con CA interna de Caddy. Instala la CA interna en los clientes antes de usarlo normalmente. `curl -k` solo es válido como prueba temporal.

## systemd

Instalar unidades:

```bash
sudo install -m 0644 infra/systemd/yt-downloader-api.service /etc/systemd/system/
sudo install -m 0644 infra/systemd/yt-downloader-worker.service /etc/systemd/system/
sudo install -m 0644 infra/systemd/yt-downloader-worker.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now yt-downloader-api.service
sudo systemctl enable --now yt-downloader-worker.timer
```

El timer lanza el worker 20 segundos después del arranque y luego 15 segundos después de que termine la ejecución anterior. El worker procesa como máximo un trabajo por ejecución. Una descarga larga mantiene el servicio activo; el timer no debe solapar dos descargas iniciadas por él. Si no hay trabajos pendientes, el worker termina y el timer vuelve a comprobar la cola.

## Comprobación

```bash
systemctl status caddy
systemctl status yt-downloader-api.service
systemctl status yt-downloader-worker.timer
systemctl list-timers yt-downloader-worker.timer
journalctl -u yt-downloader-api.service -f
journalctl -u yt-downloader-worker.service -f
curl -k https://music.example.internal/api/v1/health
```

`-k` solo es una prueba temporal antes de instalar la CA interna de Caddy en los clientes.

## Rollback

1. Deshabilita el timer: `sudo systemctl disable --now yt-downloader-worker.timer`.
2. Detén worker y API: `sudo systemctl stop yt-downloader-worker.service yt-downloader-api.service`.
3. Restaura el frontend anterior desde `/var/www/yt-downloader.previous`.
4. Restaura copias anteriores de `/etc/yt-downloader`.
5. Valida Caddy antes de recargar: `sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`.
6. Recarga o reinicia servicios solo después de validar configuración.

## Notas Operativas

`yt-dlp-ejs` y un runtime JavaScript compatible pueden ser necesarios para algunos vídeos de YouTube. No forman parte de esta instalación inicial.
