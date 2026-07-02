import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  createDirectory,
  getLibraryEntries,
  getProfiles,
  moveEntry,
  renameEntry,
  trashEntry,
} from "../api/client";
import { getUserErrorMessage } from "../api/errors";
import type { LibraryEntry } from "../api/types";
import { useSelection } from "../app/SelectionContext";
import { ProfileSelect } from "../components/ProfileSelect";
import { StatusMessage } from "../components/StatusMessage";
import { breadcrumbs, displayPath, parentPath } from "../features/library/path";

export function LibraryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const isSelecting = searchParams.get("select") === "1";
  const profileFromQuery = searchParams.get("profile") ?? "";
  const { selectedProfileId, setSelectedProfileId, setDestinationPath } = useSelection();
  const [currentPath, setCurrentPath] = useState("");
  const [isCreatingDirectory, setIsCreatingDirectory] = useState(false);
  const [directoryName, setDirectoryName] = useState("");
  const [editingEntryPath, setEditingEntryPath] = useState("");
  const [editingEntryName, setEditingEntryName] = useState("");
  const [movingEntry, setMovingEntry] = useState<LibraryEntry | null>(null);
  const [moveTargetPath, setMoveTargetPath] = useState("");
  const [clientError, setClientError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

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
  const libraryQueryKey = ["library", selectedProfileId, currentPath];

  const moveEntriesQuery = useQuery({
    queryKey: ["library", selectedProfileId, moveTargetPath, "move-target"],
    queryFn: () => getLibraryEntries(selectedProfileId, moveTargetPath),
    enabled: Boolean(selectedProfileId && movingEntry),
  });

  const createDirectoryMutation = useMutation({
    mutationFn: () => createDirectory(selectedProfileId, currentPath, directoryName.trim()),
    onSuccess: async () => {
      setSuccessMessage("Carpeta creada correctamente.");
      setClientError("");
      setIsCreatingDirectory(false);
      setDirectoryName("");
      await queryClient.invalidateQueries({ queryKey: libraryQueryKey });
    },
  });

  const renameMutation = useMutation({
    mutationFn: ({ path, newName }: { path: string; newName: string }) =>
      renameEntry(selectedProfileId, path, newName),
    onSuccess: async () => {
      setSuccessMessage("Entrada renombrada correctamente.");
      setClientError("");
      setEditingEntryPath("");
      setEditingEntryName("");
      await queryClient.invalidateQueries({ queryKey: libraryQueryKey });
    },
  });

  const trashMutation = useMutation({
    mutationFn: (path: string) => trashEntry(selectedProfileId, path),
    onSuccess: async () => {
      setSuccessMessage("Entrada enviada a la papelera correctamente.");
      setClientError("");
      await queryClient.invalidateQueries({ queryKey: libraryQueryKey });
    },
  });

  const moveMutation = useMutation({
    mutationFn: ({ sourcePath, targetPath }: { sourcePath: string; targetPath: string }) =>
      moveEntry(selectedProfileId, sourcePath, targetPath),
    onSuccess: async () => {
      setSuccessMessage("Entrada movida correctamente.");
      setClientError("");
      setMovingEntry(null);
      setMoveTargetPath("");
      await queryClient.invalidateQueries({ queryKey: ["library", selectedProfileId] });
    },
  });

  const operationError =
    createDirectoryMutation.error ??
    renameMutation.error ??
    trashMutation.error ??
    moveMutation.error;
  const isMutating =
    createDirectoryMutation.isPending ||
    renameMutation.isPending ||
    trashMutation.isPending ||
    moveMutation.isPending;
  const moveValidationMessage = movingEntry
    ? getMoveValidationMessage(movingEntry, moveTargetPath)
    : "";

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
        <button
          type="button"
          className="button button-secondary"
          disabled={!selectedProfileId || isMutating}
          onClick={() => {
            setClientError("");
            setSuccessMessage("");
            setIsCreatingDirectory(true);
          }}
        >
          Crear carpeta
        </button>
      </div>

      {isCreatingDirectory ? (
        <form
          className="inline-form"
          aria-label="Crear carpeta"
          onSubmit={(event) => {
            event.preventDefault();
            const validationError = validateEntryName(directoryName);
            if (validationError) {
              setClientError(validationError);
              return;
            }
            setClientError("");
            setSuccessMessage("");
            createDirectoryMutation.mutate();
          }}
        >
          <label className="field">
            <span>Nombre de la carpeta</span>
            <input value={directoryName} onChange={(event) => setDirectoryName(event.target.value)} />
          </label>
          <button type="submit" className="button" disabled={isMutating}>
            Crear
          </button>
          <button
            type="button"
            className="button button-secondary"
            disabled={isMutating}
            onClick={() => {
              setIsCreatingDirectory(false);
              setDirectoryName("");
              setClientError("");
            }}
          >
            Cancelar
          </button>
        </form>
      ) : null}

      {successMessage ? <StatusMessage tone="success">{successMessage}</StatusMessage> : null}
      {clientError ? <StatusMessage tone="error">{clientError}</StatusMessage> : null}
      {operationError ? <StatusMessage tone="error">{getUserErrorMessage(operationError)}</StatusMessage> : null}

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
      {entries.length > 0 ? (
        <EntryList
          entries={entries}
          editingEntryPath={editingEntryPath}
          editingEntryName={editingEntryName}
          isMutating={isMutating}
          onOpenDirectory={setCurrentPath}
          onRenameStart={(entry) => {
            setClientError("");
            setSuccessMessage("");
            setEditingEntryPath(entry.path);
            setEditingEntryName(entry.name);
          }}
          onRenameCancel={() => {
            setEditingEntryPath("");
            setEditingEntryName("");
            setClientError("");
          }}
          onRenameNameChange={setEditingEntryName}
          onRenameSubmit={(entry) => {
            const validationError = validateEntryName(editingEntryName);
            if (validationError) {
              setClientError(validationError);
              return;
            }
            setClientError("");
            setSuccessMessage("");
            renameMutation.mutate({ path: entry.path, newName: editingEntryName.trim() });
          }}
          onTrash={(entry) => {
            const confirmed = window.confirm(
              `La entrada se moverá a la papelera interna del perfil. ¿Continuar con ${entry.name}?`,
            );
            if (!confirmed) {
              return;
            }
            setClientError("");
            setSuccessMessage("");
            trashMutation.mutate(entry.path);
          }}
          onMoveStart={(entry) => {
            setClientError("");
            setSuccessMessage("");
            setMovingEntry(entry);
            setMoveTargetPath("");
          }}
        />
      ) : null}
      {movingEntry ? (
        <MoveDialog
          entry={movingEntry}
          currentTargetPath={moveTargetPath}
          entries={moveEntriesQuery.data?.entries ?? []}
          isLoading={moveEntriesQuery.isLoading}
          isMutating={isMutating}
          validationMessage={moveValidationMessage}
          error={moveEntriesQuery.error}
          onNavigate={setMoveTargetPath}
          onCancel={() => {
            setMovingEntry(null);
            setMoveTargetPath("");
            setClientError("");
          }}
          onConfirm={() => {
            if (moveValidationMessage) {
              setClientError(moveValidationMessage);
              return;
            }
            setClientError("");
            setSuccessMessage("");
            moveMutation.mutate({ sourcePath: movingEntry.path, targetPath: moveTargetPath });
          }}
        />
      ) : null}
    </section>
  );
}

function EntryList({
  entries,
  editingEntryPath,
  editingEntryName,
  isMutating,
  onOpenDirectory,
  onRenameStart,
  onRenameCancel,
  onRenameNameChange,
  onRenameSubmit,
  onTrash,
  onMoveStart,
}: {
  entries: LibraryEntry[];
  editingEntryPath: string;
  editingEntryName: string;
  isMutating: boolean;
  onOpenDirectory: (path: string) => void;
  onRenameStart: (entry: LibraryEntry) => void;
  onRenameCancel: () => void;
  onRenameNameChange: (name: string) => void;
  onRenameSubmit: (entry: LibraryEntry) => void;
  onTrash: (entry: LibraryEntry) => void;
  onMoveStart: (entry: LibraryEntry) => void;
}) {
  return (
    <ul className="entry-list" aria-label="Contenido de la carpeta">
      {entries.map((entry) => (
        <li key={entry.path}>
          <div className="entry-row">
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
                <span className="muted">
                  {entry.size_bytes === null ? "Tamaño no disponible" : formatBytes(entry.size_bytes)}
                </span>
              </div>
            )}
            <div className="entry-actions">
              <button type="button" className="button button-secondary" disabled={isMutating} onClick={() => onRenameStart(entry)}>
                Renombrar
              </button>
              <button type="button" className="button button-danger" disabled={isMutating} onClick={() => onTrash(entry)}>
                Enviar a papelera
              </button>
              <button type="button" className="button button-secondary" disabled={isMutating} onClick={() => onMoveStart(entry)}>
                Mover
              </button>
            </div>
            {editingEntryPath === entry.path ? (
              <form
                className="inline-form entry-rename-form"
                aria-label={`Renombrar ${entry.name}`}
                onSubmit={(event) => {
                  event.preventDefault();
                  onRenameSubmit(entry);
                }}
              >
                <label className="field">
                  <span>Nuevo nombre</span>
                  <input value={editingEntryName} onChange={(event) => onRenameNameChange(event.target.value)} />
                </label>
                <button type="submit" className="button" disabled={isMutating}>
                  Guardar
                </button>
                <button type="button" className="button button-secondary" disabled={isMutating} onClick={onRenameCancel}>
                  Cancelar
                </button>
              </form>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

function MoveDialog({
  entry,
  currentTargetPath,
  entries,
  isLoading,
  isMutating,
  validationMessage,
  error,
  onNavigate,
  onCancel,
  onConfirm,
}: {
  entry: LibraryEntry;
  currentTargetPath: string;
  entries: LibraryEntry[];
  isLoading: boolean;
  isMutating: boolean;
  validationMessage: string;
  error: unknown;
  onNavigate: (path: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const directories = entries.filter((item) => item.type === "directory");

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  return (
    <div className="dialog-backdrop">
      <div
        className="dialog-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="move-dialog-heading"
        tabIndex={-1}
        ref={dialogRef}
      >
        <h3 id="move-dialog-heading">Mover entrada</h3>
        <p>
          Mover <strong>"{entry.name}"</strong> a <strong>{displayPath(currentTargetPath)}</strong>
        </p>
        <div className="current-location">
          <p>
            <strong>Destino actual:</strong> {displayPath(currentTargetPath)}
          </p>
        </div>
        <nav aria-label="Ruta de destino" className="breadcrumbs">
          {breadcrumbs(currentTargetPath).map((crumb, index) => (
            <button key={crumb.path || "root"} type="button" disabled={isMutating} onClick={() => onNavigate(crumb.path)}>
              {index === 0 ? "/" : crumb.label}
            </button>
          ))}
        </nav>
        <button type="button" className="button button-secondary" disabled={isMutating} onClick={() => onNavigate("")}>
          Volver a la raíz del selector
        </button>
        {currentTargetPath ? (
          <button type="button" className="link-button" disabled={isMutating} onClick={() => onNavigate(parentPath(currentTargetPath))}>
            Subir un nivel en selector
          </button>
        ) : null}
        {isLoading ? <p>Cargando carpetas destino...</p> : null}
        {error ? <StatusMessage tone="error">{getUserErrorMessage(error)}</StatusMessage> : null}
        {validationMessage ? <StatusMessage tone="info">{validationMessage}</StatusMessage> : null}
        <ul className="entry-list" aria-label="Carpetas destino disponibles">
          {directories.map((directory) => (
            <li key={directory.path}>
              <button
                type="button"
                className="entry-button"
                disabled={isMutating || isForbiddenMoveTarget(entry, directory.path)}
                onClick={() => onNavigate(directory.path)}
              >
                <span aria-hidden="true">[Carpeta]</span>
                <span>{directory.name}</span>
                <span className="muted">{displayPath(directory.path)}</span>
              </button>
            </li>
          ))}
        </ul>
        {directories.length === 0 && !isLoading ? <p>No hay subcarpetas en este destino.</p> : null}
        <div className="dialog-actions">
          <button type="button" className="button button-secondary" disabled={isMutating} onClick={onCancel}>
            Cancelar
          </button>
          <button type="button" className="button" disabled={isMutating || Boolean(validationMessage)} onClick={onConfirm}>
            {isMutating ? "Moviendo..." : "Mover aquí"}
          </button>
        </div>
      </div>
    </div>
  );
}

function validateEntryName(value: string): string {
  const name = value.trim();
  if (!name) {
    return "El nombre es obligatorio.";
  }
  if (name.includes("/") || name.includes("\\")) {
    return "El nombre no puede contener separadores de ruta.";
  }
  if (name === "." || name === ".." || name.startsWith(".")) {
    return "El nombre no puede ser oculto ni reservado.";
  }
  return "";
}

function getMoveValidationMessage(entry: LibraryEntry, targetPath: string): string {
  if (targetPath === parentPath(entry.path)) {
    return "La entrada ya se encuentra en esta carpeta.";
  }
  if (isForbiddenMoveTarget(entry, targetPath)) {
    return "No se puede mover una carpeta dentro de sí misma.";
  }
  return "";
}

function isForbiddenMoveTarget(entry: LibraryEntry, targetPath: string): boolean {
  if (entry.type !== "directory") {
    return false;
  }
  return targetPath === entry.path || targetPath.startsWith(`${entry.path}/`);
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
