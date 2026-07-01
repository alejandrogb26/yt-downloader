import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { getLibraryEntries, getProfiles } from "../api/client";
import { getUserErrorMessage } from "../api/errors";
import type { LibraryEntry } from "../api/types";
import { useSelection } from "../app/SelectionContext";
import { ProfileSelect } from "../components/ProfileSelect";
import { StatusMessage } from "../components/StatusMessage";
import { breadcrumbs, displayPath, parentPath } from "../features/library/path";

export function LibraryPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isSelecting = searchParams.get("select") === "1";
  const profileFromQuery = searchParams.get("profile") ?? "";
  const { selectedProfileId, setSelectedProfileId, setDestinationPath } = useSelection();
  const [currentPath, setCurrentPath] = useState("");

  const profilesQuery = useQuery({ queryKey: ["profiles"], queryFn: getProfiles });
  const profiles = useMemo(() => profilesQuery.data?.profiles ?? [], [profilesQuery.data]);

  useEffect(() => {
    if (profileFromQuery) {
      setSelectedProfileId(profileFromQuery);
      return;
    }
    if (!selectedProfileId && profiles.length > 0) {
      setSelectedProfileId(profiles[0].id);
    }
  }, [profileFromQuery, profiles, selectedProfileId, setSelectedProfileId]);

  const entriesQuery = useQuery({
    queryKey: ["library", selectedProfileId, currentPath],
    queryFn: () => getLibraryEntries(selectedProfileId, currentPath),
    enabled: Boolean(selectedProfileId),
  });

  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId);
  const entries = entriesQuery.data?.entries ?? [];

  return (
    <section className="panel" aria-labelledby="library-heading">
      <div className="panel-heading-row">
        <div>
          <h2 id="library-heading">Biblioteca</h2>
          <p className="muted">Explorador de solo lectura para elegir una carpeta destino.</p>
        </div>
        {isSelecting ? <Link to="/downloads">Volver a descargas</Link> : null}
      </div>

      {profilesQuery.isLoading ? <p>Cargando perfiles...</p> : null}
      {profilesQuery.isError ? (
        <StatusMessage tone="error">{getUserErrorMessage(profilesQuery.error)}</StatusMessage>
      ) : null}
      {!profilesQuery.isLoading && profiles.length === 0 ? (
        <StatusMessage tone="info">No hay perfiles disponibles.</StatusMessage>
      ) : null}

      <div className="library-toolbar">
        <ProfileSelect
          profiles={profiles}
          value={selectedProfileId}
          onChange={(profileId) => {
            setSelectedProfileId(profileId);
            setCurrentPath("");
          }}
        />
        <button type="button" className="button button-secondary" onClick={() => setCurrentPath("")}>
          Volver a la raíz
        </button>
        <button
          type="button"
          className="button"
          disabled={!selectedProfileId}
          onClick={() => {
            setDestinationPath(currentPath);
            navigate("/downloads");
          }}
        >
          Seleccionar esta carpeta
        </button>
      </div>

      <div className="current-location" aria-live="polite">
        <p>
          <strong>Perfil:</strong> {selectedProfile?.display_name ?? "Sin perfil"}
        </p>
        <p>
          <strong>Ruta:</strong> {displayPath(currentPath)}
        </p>
      </div>

      <nav aria-label="Ruta actual" className="breadcrumbs">
        {breadcrumbs(currentPath).map((crumb, index) => (
          <button key={crumb.path || "root"} type="button" onClick={() => setCurrentPath(crumb.path)}>
            {index === 0 ? "/" : crumb.label}
          </button>
        ))}
      </nav>

      {currentPath ? (
        <button type="button" className="link-button" onClick={() => setCurrentPath(parentPath(currentPath))}>
          Subir un nivel
        </button>
      ) : null}

      {entriesQuery.isLoading ? <p>Cargando biblioteca...</p> : null}
      {entriesQuery.isError ? (
        <StatusMessage tone="error">{getUserErrorMessage(entriesQuery.error)}</StatusMessage>
      ) : null}
      {!entriesQuery.isLoading && selectedProfileId && entries.length === 0 ? (
        <p>Esta carpeta está vacía.</p>
      ) : null}
      {entries.length > 0 ? <EntryList entries={entries} onOpenDirectory={setCurrentPath} /> : null}
    </section>
  );
}

function EntryList({
  entries,
  onOpenDirectory,
}: {
  entries: LibraryEntry[];
  onOpenDirectory: (path: string) => void;
}) {
  return (
    <ul className="entry-list" aria-label="Contenido de la carpeta">
      {entries.map((entry) => (
        <li key={entry.path}>
          {entry.type === "directory" ? (
            <button type="button" className="entry-button" onClick={() => onOpenDirectory(entry.path)}>
              <span aria-hidden="true">[Carpeta]</span>
              <span>{entry.name}</span>
              <span className="muted">{displayPath(entry.path)}</span>
            </button>
          ) : (
            <div className="entry-file">
              <span aria-hidden="true">[Archivo]</span>
              <span>{entry.name}</span>
              <span className="muted">{entry.size_bytes === null ? "Tamaño no disponible" : formatBytes(entry.size_bytes)}</span>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
