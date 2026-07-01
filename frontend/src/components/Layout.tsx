import { NavLink, Outlet } from "react-router-dom";

export function Layout() {
  return (
    <div className="app-shell">
      <header className="site-header">
        <div>
          <p className="eyebrow">yt-downloader</p>
          <h1>Gestor de descargas</h1>
        </div>
        <nav aria-label="Navegación principal" className="main-nav">
          <NavLink to="/downloads">Descargas</NavLink>
          <NavLink to="/library">Biblioteca</NavLink>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
