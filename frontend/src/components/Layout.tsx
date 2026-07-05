import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useTheme } from "../app/ThemeContext";
import { IconButton } from "./ui";

export function Layout() {
  const location = useLocation();
  const { theme, setTheme } = useTheme();
  const isDownloads = location.pathname.startsWith("/downloads") || location.pathname === "/";
  const title = isDownloads ? "Descargas" : "Biblioteca";
  const subtitle = isDownloads
    ? "Crea trabajos y sigue la cola de audio."
    : "Explora perfiles y elige destinos sin cargar todo el NFS.";

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Navegación principal">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ▶
          </span>
          <div>
            <p>yt-downloader</p>
            <strong>Audio LAN</strong>
          </div>
        </div>
        <nav className="side-nav">
          <NavLink to="/downloads">
            <span aria-hidden="true">↓</span>
            Descargas
          </NavLink>
          <NavLink to="/library">
            <span aria-hidden="true">▦</span>
            Biblioteca
          </NavLink>
        </nav>
      </aside>

      <div className="content-shell">
        <header className="topbar">
          <div>
            <p className="eyebrow">yt-downloader</p>
            <h1>{title}</h1>
            <p className="topbar-subtitle">{subtitle}</p>
          </div>
          <IconButton
            label={theme === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro"}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
          </IconButton>
        </header>

        <main className="page-content">
          <Outlet />
        </main>
      </div>

      <nav className="mobile-nav" aria-label="Navegación principal móvil">
        <NavLink to="/downloads">
          <span aria-hidden="true">↓</span>
          Descargas
        </NavLink>
        <NavLink to="/library">
          <span aria-hidden="true">▦</span>
          Biblioteca
        </NavLink>
      </nav>
    </div>
  );
}
