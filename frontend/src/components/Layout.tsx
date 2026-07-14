import { Navigate, NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../app/useAuth";
import { useTheme } from "../app/ThemeContext";
import { Button, IconButton } from "./ui";

export function Layout() {
  const location = useLocation();
  const { theme, setTheme } = useTheme();
  const auth = useAuth();
  if (auth.loading) {
    return <main className="page-content">Comprobando sesión...</main>;
  }
  if (!auth.user) {
    return <Navigate to="/login" replace />;
  }
  const isDownloads = location.pathname.startsWith("/downloads") || location.pathname === "/";
  const title = isDownloads ? "Descargas" : "Biblioteca";
  const subtitle = isDownloads
    ? "Crea trabajos y sigue la cola de audio."
    : "Explora perfiles y elige destinos sin cargar todo el NFS.";
  const userLabel = auth.user.display_name || auth.user.username;

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
          <div className="topbar-actions">
            <IconButton
              label={theme === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro"}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
            </IconButton>
            <div className="session-pill" aria-label={`Sesión iniciada como ${userLabel}`}>
              <span>{userLabel}</span>
              <Button variant="secondary" onClick={() => void auth.logout()}>
                Salir
              </Button>
            </div>
          </div>
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
