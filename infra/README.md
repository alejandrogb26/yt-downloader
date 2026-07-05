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
worker systemd timer → staging local → NFS por perfil
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
- Perfiles: `/etc/yt-downloader/profiles.json`
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

`LIBRARY_EXCLUSIONS_CONFIG_PATH` apunta al JSON de exclusiones de navegador. El formato es `{"excluded_names":["@eaDir"]}`. Los nombres son nombres base exactos, sin rutas ni patrones; si el fichero no existe, la API usa una lista vacía.

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

La configuración escucha en HTTP interno `IP_CT:8081`, enlazada solo a `IP_CT`. Sirve `/var/www/yt-downloader`, soporta rutas SPA con fallback a `/index.html`, y reenvía solo `/api/*` a `127.0.0.1:8080` sin reescribir la ruta. No incluye reglas especiales para `/docs` ni `/openapi.json`.

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
curl https://music.alejandrogb.local/api/v1/health
curl -H 'Host: music.alejandrogb.local' http://IP_CT:8081/api/v1/health
findmnt -T /mnt/music/alejandrogb
findmnt -T /mnt/music/pepe
```

El primer `curl` se ejecuta desde un cliente LAN y pasa por Nginx central. El segundo `curl` se ejecuta desde el CT para comprobar Caddy directamente sin depender del DNS público interno. Los comandos `findmnt` verifican montajes concretos de perfiles.

## Rollback

1. Deshabilita el timer: `sudo systemctl disable --now yt-downloader-worker.timer`.
2. Detén worker y API: `sudo systemctl stop yt-downloader-worker.service yt-downloader-api.service`.
3. Restaura el frontend anterior desde `/var/www/yt-downloader.previous`.
4. Restaura copias anteriores de `/etc/yt-downloader`.
5. Valida Caddy antes de recargar: `sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`.
6. Recarga o reinicia servicios solo después de validar configuración.

## Notas Operativas

`yt-dlp-ejs` y un runtime JavaScript compatible pueden ser necesarios para algunos vídeos de YouTube. No forman parte de esta instalación inicial.
