# Frontend

Frontend separado de `yt-downloader`, implementado con React, TypeScript y Vite. Permite seleccionar un perfil, navegar la biblioteca en modo solo lectura, elegir una carpeta destino, crear trabajos de descarga y consultar trabajos recientes.

## Requisitos

- Node.js compatible con Vite.
- `npm`.
- API FastAPI disponible en desarrollo en `http://127.0.0.1:8080`.

## Instalación

```bash
npm install
```

## Variables de Entorno

Ejemplo versionable en `.env.example`:

```env
VITE_API_BASE_URL=/api/v1
```

No se configuran hosts, credenciales ni URLs de MariaDB en el frontend.

## Ejecución

```bash
npm run dev
```

Vite sirve el frontend en desarrollo y reenvía las peticiones que empiezan por `/api` a `http://127.0.0.1:8080`. Este proxy es solo de desarrollo; no se añade CORS al backend.

## Pruebas y Calidad

```bash
npm run test:run
npm run lint
```

Las pruebas usan Vitest y Testing Library con `fetch` simulado. No acceden a MariaDB, NFS, YouTube ni a la API real.

## Build

```bash
npm run build
```

El resultado queda en `dist/`. En producción se servirá como archivos estáticos mediante Caddy en una fase posterior. Este proyecto no añade un servidor Node de producción.

## Arquitectura

- `src/api`: cliente HTTP tipado y tipos de contratos de API.
- `src/app`: router, Query Client y estado compartido de perfil/destino.
- `src/pages`: páginas principales `/downloads` y `/library`.
- `src/features`: lógica específica de descargas y biblioteca.
- `src/components`: componentes reutilizables.
- `src/styles`: CSS propio.

El navegador nunca accede directamente al NFS ni recibe rutas reales del sistema. Toda la comunicación pasa por la API HTTP existente bajo `/api/v1`.
