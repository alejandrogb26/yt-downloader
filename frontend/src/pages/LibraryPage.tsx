import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  createDirectory,
  getLibraryEntries,
  getProfiles,
  moveEntry,
  renameEntry,
  searchLibrary,
  trashEntry,
} from "../api/client";
import { getUserErrorMessage } from "../api/errors";
import type { LibraryEntry } from "../api/types";
import { useSelection } from "../app/SelectionContext";
import { ProfileSelect } from "../components/ProfileSelect";
import { StatusMessage } from "../components/StatusMessage";
import { Button, Card, EmptyState, Field, IconButton, Skeleton, TextInput } from "../components/ui";
import { breadcrumbs, displayPath, parentPath } from "../features/library/path";

export function LibraryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const isSelecting = searchParams.get("select") === "1";
  const profileFromQuery = searchParams.get("profile") ?? "";
  const { selectedProfileId, setSelectedProfileId, setDestinationPath } = useSelection();
  const [currentPath, setCurrentPath] = useState("");
  const [selectedEntryPath, setSelectedEntryPath] = useState("");
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(() => new Set([""]));
  const [isTreeOpen, setIsTreeOpen] = useState(false);
  const [isCreatingDirectory, setIsCreatingDirectory] = useState(false);
  const [directoryName, setDirectoryName] = useState("");
  const [renamingEntry, setRenamingEntry] = useState<LibraryEntry | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [movingEntry, setMovingEntry] = useState<LibraryEntry | null>(null);
  const [moveTargetPath, setMoveTargetPath] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [clientError, setClientError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const pendingSelectedEntryPath = useRef("");

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

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(searchInput.trim());
    }, 350);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const isSearchActive = debouncedSearch.length >= 2;
  const searchQuery = useQuery({
    queryKey: ["library-search", selectedProfileId, debouncedSearch],
    queryFn: ({ signal }) => searchLibrary(selectedProfileId, debouncedSearch, 50, signal),
    enabled: Boolean(selectedProfileId && isSearchActive),
  });

  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId);
  const entries = entriesQuery.data?.entries ?? [];
  const directories = entries.filter((entry) => entry.type === "directory");
  const selectedEntry = entries.find((entry) => entry.path === selectedEntryPath) ?? null;
  const libraryQueryKey = ["library", selectedProfileId, currentPath];

  const moveEntriesQuery = useQuery({
    queryKey: ["library", selectedProfileId, moveTargetPath, "move-target"],
    queryFn: () => getLibraryEntries(selectedProfileId, moveTargetPath),
    enabled: Boolean(selectedProfileId && movingEntry),
  });

  useEffect(() => {
    if (pendingSelectedEntryPath.current) {
      setSelectedEntryPath(pendingSelectedEntryPath.current);
      pendingSelectedEntryPath.current = "";
      return;
    }
    setSelectedEntryPath("");
  }, [currentPath, selectedProfileId]);

  const createDirectoryMutation = useMutation({
    mutationFn: () => createDirectory(selectedProfileId, currentPath, directoryName.trim()),
    onSuccess: async () => {
      setSuccessMessage("Carpeta creada correctamente.");
      setClientError("");
      setIsCreatingDirectory(false);
      setDirectoryName("");
      await invalidateLibrary(queryClient, selectedProfileId, currentPath);
    },
  });

  const renameMutation = useMutation({
    mutationFn: ({ path, newName }: { path: string; newName: string }) =>
      renameEntry(selectedProfileId, path, newName),
    onSuccess: async () => {
      setSuccessMessage("Entrada renombrada correctamente.");
      setClientError("");
      setRenamingEntry(null);
      setRenameValue("");
      await queryClient.invalidateQueries({ queryKey: libraryQueryKey });
    },
  });

  const trashMutation = useMutation({
    mutationFn: (path: string) => trashEntry(selectedProfileId, path),
    onSuccess: async () => {
      setSuccessMessage("Entrada enviada a la papelera correctamente.");
      setClientError("");
      setSelectedEntryPath("");
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
      setSelectedEntryPath("");
      await queryClient.invalidateQueries({ queryKey: ["library", selectedProfileId] });
    },
  });

  const operationError =
    createDirectoryMutation.error ?? renameMutation.error ?? trashMutation.error ?? moveMutation.error;
  const isMutating =
    createDirectoryMutation.isPending ||
    renameMutation.isPending ||
    trashMutation.isPending ||
    moveMutation.isPending;
  const moveValidationMessage = movingEntry ? getMoveValidationMessage(movingEntry, moveTargetPath) : "";

  const openDirectory = (path: string) => {
    setCurrentPath(path);
    setExpandedPaths((previous) => new Set(previous).add(path));
    setIsTreeOpen(false);
  };

  const openSearchResult = (entry: LibraryEntry) => {
    if (entry.type === "directory") {
      openDirectory(entry.path);
      setSelectedEntryPath("");
      return;
    }
    const containingPath = parentPath(entry.path);
    pendingSelectedEntryPath.current = entry.path;
    openDirectory(containingPath);
  };

  const clearSearch = () => {
    setSearchInput("");
    setDebouncedSearch("");
  };

  const selectedPathLabel = displayPath(currentPath);

  return (
    <div className="library-page">
      <section className="page-hero page-hero--library">
        <div>
          <p className="eyebrow">Explorador NFS</p>
          <h2>Biblioteca</h2>
          <p>
            Navega por carpetas bajo demanda, gestiona entradas y selecciona destinos de descarga
            sin exponer rutas internas al navegador.
          </p>
        </div>
        <div className="hero-actions">
          {isSelecting ? <Link to="/downloads">Volver a descargas</Link> : null}
          <ProfileSelect
            profiles={profiles}
            value={selectedProfileId}
            onChange={(profileId) => {
              setSelectedProfileId(profileId);
              setCurrentPath("");
              clearSearch();
              setExpandedPaths(new Set([""]));
            }}
            disabled={profilesQuery.isLoading}
          />
        </div>
      </section>

      {profilesQuery.isLoading ? <Skeleton label="Cargando perfiles" /> : null}
      {profilesQuery.isError ? (
        <StatusMessage tone="error">{getUserErrorMessage(profilesQuery.error)}</StatusMessage>
      ) : null}
      {!profilesQuery.isLoading && profiles.length === 0 ? (
        <StatusMessage tone="info">No hay perfiles disponibles.</StatusMessage>
      ) : null}
      {successMessage ? <StatusMessage tone="success">{successMessage}</StatusMessage> : null}
      {clientError ? <StatusMessage tone="error">{clientError}</StatusMessage> : null}
      {operationError ? <StatusMessage tone="error">{getUserErrorMessage(operationError)}</StatusMessage> : null}

      <div className="library-layout">
        <Card className={`folder-panel ${isTreeOpen ? "folder-panel--open" : ""}`} aria-label="Árbol de carpetas">
          <div className="panel-title-row">
            <div>
              <h3>Carpetas</h3>
              <p>{selectedProfile?.display_name ?? "Sin perfil"}</p>
            </div>
            <IconButton label="Cerrar panel de carpetas" className="mobile-only" onClick={() => setIsTreeOpen(false)}>
              <span aria-hidden="true">×</span>
            </IconButton>
          </div>
          <FolderTree
            profileId={selectedProfileId}
            currentPath={currentPath}
            expandedPaths={expandedPaths}
            onSelect={openDirectory}
            onToggle={(path) => {
              setExpandedPaths((previous) => {
                const next = new Set(previous);
                if (next.has(path)) {
                  next.delete(path);
                } else {
                  next.add(path);
                }
                return next;
              });
            }}
          />
        </Card>

        <Card className="content-panel" aria-labelledby="library-content-heading">
          <div className="library-topline">
            <Button variant="secondary" className="mobile-only" onClick={() => setIsTreeOpen(true)}>
              Carpetas
            </Button>
            <div>
              <h2 id="library-content-heading">{selectedPathLabel}</h2>
              <p>{directories.length} carpetas, {entries.length - directories.length} archivos</p>
            </div>
          </div>

          <nav aria-label="Ruta actual" className="breadcrumbs">
            {breadcrumbs(currentPath).map((crumb, index) => (
              <button key={crumb.path || "root"} type="button" onClick={() => openDirectory(crumb.path)}>
                {index === 0 ? "Inicio" : crumb.label}
              </button>
            ))}
          </nav>

          <div className="library-searchbar" role="search">
            <Field label="Buscar en el perfil seleccionado">
              <TextInput
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Buscar carpetas y archivos en esta biblioteca"
              />
            </Field>
            <Button type="button" variant="secondary" disabled={!searchInput} onClick={clearSearch}>
              Limpiar búsqueda
            </Button>
            <p>Ámbito: biblioteca completa de {selectedProfile?.display_name ?? "este perfil"}.</p>
          </div>

          <div className="library-commandbar">
            <Button variant="secondary" disabled={!currentPath} onClick={() => openDirectory(parentPath(currentPath))}>
              Subir
            </Button>
            <Button
              variant="primary"
              disabled={!selectedProfileId}
              onClick={() => {
                setDestinationPath(currentPath);
                navigate("/downloads");
              }}
            >
              Seleccionar esta carpeta
            </Button>
            <Button
              variant="secondary"
              disabled={!selectedProfileId || isMutating}
              onClick={() => {
                setClientError("");
                setSuccessMessage("");
                setIsCreatingDirectory(true);
              }}
            >
              Crear carpeta
            </Button>
            <ActionMenu
              entry={selectedEntry}
              disabled={isMutating}
              onOpen={() => selectedEntry?.type === "directory" && openDirectory(selectedEntry.path)}
              onRename={() => {
                if (!selectedEntry) return;
                setClientError("");
                setSuccessMessage("");
                setRenamingEntry(selectedEntry);
                setRenameValue(selectedEntry.name);
              }}
              onMove={() => {
                if (!selectedEntry) return;
                setClientError("");
                setSuccessMessage("");
                setMovingEntry(selectedEntry);
                setMoveTargetPath("");
              }}
              onTrash={() => {
                if (!selectedEntry) return;
                const confirmed = window.confirm(
                  `La entrada se moverá a la papelera interna del perfil. ¿Continuar con ${selectedEntry.name}?`,
                );
                if (!confirmed) return;
                setClientError("");
                setSuccessMessage("");
                trashMutation.mutate(selectedEntry.path);
              }}
            />
          </div>

          {isCreatingDirectory ? (
            <form
              className="inline-form create-folder-form"
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
              <Field label="Nombre de la carpeta">
                <TextInput value={directoryName} onChange={(event) => setDirectoryName(event.target.value)} autoFocus />
              </Field>
              <Button type="submit" disabled={isMutating}>Crear</Button>
              <Button
                type="button"
                variant="secondary"
                disabled={isMutating}
                onClick={() => {
                  setIsCreatingDirectory(false);
                  setDirectoryName("");
                  setClientError("");
                }}
              >
                Cancelar
              </Button>
            </form>
          ) : null}

          {searchInput.trim().length > 0 && searchInput.trim().length < 2 ? (
            <StatusMessage tone="info">Escribe al menos 2 caracteres para buscar.</StatusMessage>
          ) : null}
          {isSearchActive ? (
            <SearchResults
              query={debouncedSearch}
              response={searchQuery.data}
              isLoading={searchQuery.isLoading || searchQuery.isFetching}
              error={searchQuery.error}
              onOpen={openSearchResult}
            />
          ) : null}
          {!isSearchActive && entriesQuery.isLoading ? <Skeleton label="Cargando biblioteca" /> : null}
          {!isSearchActive && entriesQuery.isError ? (
            <StatusMessage tone="error">{getUserErrorMessage(entriesQuery.error)}</StatusMessage>
          ) : null}
          {!isSearchActive && !entriesQuery.isLoading && selectedProfileId && entries.length === 0 ? (
            <EmptyState title="Carpeta vacía">
              Crea una carpeta, selecciona este destino o vuelve a una carpeta superior.
            </EmptyState>
          ) : null}
          {!isSearchActive && entries.length > 0 ? (
            <EntryGrid
              entries={entries}
              selectedEntryPath={selectedEntryPath}
              onSelect={setSelectedEntryPath}
              onOpenDirectory={openDirectory}
            />
          ) : null}
        </Card>
      </div>

      {isTreeOpen ? <button className="drawer-scrim" aria-label="Cerrar carpetas" onClick={() => setIsTreeOpen(false)} /> : null}

      {renamingEntry ? (
        <RenameDialog
          entry={renamingEntry}
          value={renameValue}
          isMutating={isMutating}
          onChange={setRenameValue}
          onCancel={() => {
            setRenamingEntry(null);
            setRenameValue("");
            setClientError("");
          }}
          onConfirm={() => {
            const validationError = validateEntryName(renameValue);
            if (validationError) {
              setClientError(validationError);
              return;
            }
            setClientError("");
            setSuccessMessage("");
            renameMutation.mutate({ path: renamingEntry.path, newName: renameValue.trim() });
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
    </div>
  );
}

function SearchResults({
  query,
  response,
  isLoading,
  error,
  onOpen,
}: {
  query: string;
  response: { results: LibraryEntry[]; truncated: boolean; limit: number } | undefined;
  isLoading: boolean;
  error: unknown;
  onOpen: (entry: LibraryEntry) => void;
}) {
  const results = response?.results ?? [];
  return (
    <section className="search-results" aria-label="Resultados de búsqueda">
      <div className="search-results-heading">
        <div>
          <h3>Resultados para “{query}”</h3>
          <p>Se busca por nombre en todo el perfil seleccionado.</p>
        </div>
        {response?.truncated ? <span>Se muestran solo los primeros {response.limit} resultados.</span> : null}
      </div>
      {isLoading ? <Skeleton label="Buscando en la biblioteca" /> : null}
      {error ? <StatusMessage tone="error">{getUserErrorMessage(error)}</StatusMessage> : null}
      {!isLoading && !error && results.length === 0 ? (
        <EmptyState title="Sin resultados">No se han encontrado carpetas ni archivos con ese nombre.</EmptyState>
      ) : null}
      {results.length > 0 ? (
        <div className="entry-grid search-result-grid" role="list">
          {results.map((entry) => (
            <button
              type="button"
              role="listitem"
              key={entry.path}
              className="entry-card search-result-card"
              onClick={() => onOpen(entry)}
            >
              <span className="entry-icon" aria-hidden="true">{entry.type === "directory" ? "📁" : "♪"}</span>
              <span className="entry-name">{entry.name}</span>
              <span className="entry-meta">
                {entry.type === "directory" ? "Carpeta" : `Archivo · ${formatBytes(entry.size_bytes)}`}
              </span>
              <span className="entry-path">{displayPath(entry.path)}</span>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function FolderTree({
  profileId,
  currentPath,
  expandedPaths,
  onSelect,
  onToggle,
}: {
  profileId: string;
  currentPath: string;
  expandedPaths: Set<string>;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
}) {
  if (!profileId) {
    return <EmptyState title="Sin perfil">Selecciona un perfil para ver sus carpetas.</EmptyState>;
  }
  return (
    <ul className="folder-tree" aria-label="Carpetas de biblioteca">
      <FolderNode
        profileId={profileId}
        path=""
        name="Inicio"
        level={0}
        currentPath={currentPath}
        expandedPaths={expandedPaths}
        onSelect={onSelect}
        onToggle={onToggle}
      />
    </ul>
  );
}

function FolderNode({
  profileId,
  path,
  name,
  level,
  currentPath,
  expandedPaths,
  onSelect,
  onToggle,
}: {
  profileId: string;
  path: string;
  name: string;
  level: number;
  currentPath: string;
  expandedPaths: Set<string>;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
}) {
  const isExpanded = expandedPaths.has(path);
  const query = useQuery({
    queryKey: ["library", profileId, path],
    queryFn: () => getLibraryEntries(profileId, path),
    enabled: Boolean(profileId && isExpanded),
  });
  const directories = (query.data?.entries ?? []).filter((entry) => entry.type === "directory");

  return (
    <li>
      <div className="folder-node" style={{ paddingLeft: `${level * 12}px` }}>
        <button
          type="button"
          className="folder-chevron"
          aria-label={isExpanded ? `Contraer ${name}` : `Expandir ${name}`}
          aria-expanded={isExpanded}
          onClick={() => onToggle(path)}
        >
          <span aria-hidden="true">{isExpanded ? "▾" : "▸"}</span>
        </button>
        <button
          type="button"
          className={currentPath === path ? "folder-label folder-label--active" : "folder-label"}
          onClick={() => onSelect(path)}
        >
          <span aria-hidden="true">📁</span>
          {name}
        </button>
      </div>
      {isExpanded ? (
        <div className="folder-children">
          {query.isLoading ? <span className="tree-loading">Cargando...</span> : null}
          {directories.length > 0 ? (
            <ul>
              {directories.map((directory) => (
                <FolderNode
                  key={directory.path}
                  profileId={profileId}
                  path={directory.path}
                  name={directory.name}
                  level={level + 1}
                  currentPath={currentPath}
                  expandedPaths={expandedPaths}
                  onSelect={onSelect}
                  onToggle={onToggle}
                />
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function EntryGrid({
  entries,
  selectedEntryPath,
  onSelect,
  onOpenDirectory,
}: {
  entries: LibraryEntry[];
  selectedEntryPath: string;
  onSelect: (path: string) => void;
  onOpenDirectory: (path: string) => void;
}) {
  return (
    <div className="entry-grid" aria-label="Contenido de la carpeta" role="list">
      {entries.map((entry) => (
        <button
          type="button"
          role="listitem"
          key={entry.path}
          aria-label={`Seleccionar ${entry.name}`}
          className={selectedEntryPath === entry.path ? "entry-card entry-card--selected" : "entry-card"}
          onClick={() => onSelect(entry.path)}
          onDoubleClick={() => entry.type === "directory" && onOpenDirectory(entry.path)}
        >
          <span className="entry-icon" aria-hidden="true">{entry.type === "directory" ? "📁" : "♪"}</span>
          <span className="entry-name">{entry.name}</span>
          <span className="entry-meta">
            {entry.type === "directory" ? "Carpeta" : `Archivo · ${formatBytes(entry.size_bytes)}`}
          </span>
          <span className="entry-path">{displayPath(entry.path)}</span>
        </button>
      ))}
    </div>
  );
}

function ActionMenu({
  entry,
  disabled,
  onOpen,
  onRename,
  onMove,
  onTrash,
}: {
  entry: LibraryEntry | null;
  disabled: boolean;
  onOpen: () => void;
  onRename: () => void;
  onMove: () => void;
  onTrash: () => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  const run = (callback: () => void) => {
    callback();
    setIsOpen(false);
  };

  return (
    <div className="action-menu" ref={menuRef}>
      <Button
        type="button"
        variant="secondary"
        disabled={!entry || disabled}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((value) => !value)}
      >
        Acciones...
      </Button>
      {isOpen && entry ? (
        <div className="action-menu-panel" role="menu">
          {entry.type === "directory" ? (
            <button type="button" role="menuitem" onClick={() => run(onOpen)}>Abrir carpeta</button>
          ) : null}
          <button type="button" role="menuitem" onClick={() => run(onRename)}>Renombrar</button>
          <button type="button" role="menuitem" onClick={() => run(onMove)}>Mover</button>
          <button type="button" role="menuitem" className="danger-item" onClick={() => run(onTrash)}>
            Enviar a papelera
          </button>
        </div>
      ) : null}
    </div>
  );
}

function RenameDialog({
  entry,
  value,
  isMutating,
  onChange,
  onCancel,
  onConfirm,
}: {
  entry: LibraryEntry;
  value: string;
  isMutating: boolean;
  onChange: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="dialog-backdrop">
      <form
        className="dialog-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rename-dialog-heading"
        aria-label={`Renombrar ${entry.name}`}
        onSubmit={(event) => {
          event.preventDefault();
          onConfirm();
        }}
      >
        <h3 id="rename-dialog-heading">Renombrar entrada</h3>
        <Field label="Nuevo nombre">
          <TextInput value={value} onChange={(event) => onChange(event.target.value)} autoFocus />
        </Field>
        <div className="dialog-actions">
          <Button type="button" variant="secondary" disabled={isMutating} onClick={onCancel}>Cancelar</Button>
          <Button type="submit" disabled={isMutating}>Guardar</Button>
        </div>
      </form>
    </div>
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
  const directories = entries.filter((item) => item.type === "directory");

  return (
    <div className="dialog-backdrop">
      <div className="dialog-panel" role="dialog" aria-modal="true" aria-labelledby="move-dialog-heading" tabIndex={-1}>
        <h3 id="move-dialog-heading">Mover entrada</h3>
        <p>
          Mover <strong>{entry.name}</strong> a <strong>{displayPath(currentTargetPath)}</strong>
        </p>
        <nav aria-label="Ruta de destino" className="breadcrumbs">
          {breadcrumbs(currentTargetPath).map((crumb, index) => (
            <button key={crumb.path || "root"} type="button" disabled={isMutating} onClick={() => onNavigate(crumb.path)}>
              {index === 0 ? "Inicio" : crumb.label}
            </button>
          ))}
        </nav>
        <div className="library-commandbar">
          <Button variant="secondary" disabled={!currentTargetPath || isMutating} onClick={() => onNavigate(parentPath(currentTargetPath))}>
            Subir
          </Button>
          <Button variant="secondary" disabled={isMutating} onClick={() => onNavigate("")}>Raíz</Button>
        </div>
        {isLoading ? <Skeleton label="Cargando carpetas destino" /> : null}
        {error ? <StatusMessage tone="error">{getUserErrorMessage(error)}</StatusMessage> : null}
        {validationMessage ? <StatusMessage tone="info">{validationMessage}</StatusMessage> : null}
        <div className="entry-grid entry-grid--compact" aria-label="Carpetas destino disponibles">
          {directories.map((directory) => (
            <button
              type="button"
              key={directory.path}
              className="entry-card"
              disabled={isMutating || isForbiddenMoveTarget(entry, directory.path)}
              onClick={() => onNavigate(directory.path)}
            >
              <span className="entry-icon" aria-hidden="true">📁</span>
              <span className="entry-name">{directory.name}</span>
              <span className="entry-path">{displayPath(directory.path)}</span>
            </button>
          ))}
        </div>
        {directories.length === 0 && !isLoading ? <EmptyState title="Sin subcarpetas">Puedes mover aquí o subir de nivel.</EmptyState> : null}
        <div className="dialog-actions">
          <Button type="button" variant="secondary" disabled={isMutating} onClick={onCancel}>Cancelar</Button>
          <Button type="button" disabled={isMutating || Boolean(validationMessage)} onClick={onConfirm}>
            {isMutating ? "Moviendo..." : "Mover aquí"}
          </Button>
        </div>
      </div>
    </div>
  );
}

async function invalidateLibrary(queryClient: ReturnType<typeof useQueryClient>, profileId: string, path: string) {
  await queryClient.invalidateQueries({ queryKey: ["library", profileId, path] });
}

function validateEntryName(value: string): string {
  const name = value.trim();
  if (!name) return "El nombre es obligatorio.";
  if (name.includes("/") || name.includes("\\")) return "El nombre no puede contener separadores de ruta.";
  if (name === "." || name === ".." || name.startsWith(".")) return "El nombre no puede ser oculto ni reservado.";
  return "";
}

function getMoveValidationMessage(entry: LibraryEntry, targetPath: string): string {
  if (targetPath === parentPath(entry.path)) return "La entrada ya se encuentra en esta carpeta.";
  if (isForbiddenMoveTarget(entry, targetPath)) return "No se puede mover una carpeta dentro de sí misma.";
  return "";
}

function isForbiddenMoveTarget(entry: LibraryEntry, targetPath: string): boolean {
  if (entry.type !== "directory") return false;
  return targetPath === entry.path || targetPath.startsWith(`${entry.path}/`);
}

function formatBytes(value: number | null): string {
  if (value === null) return "Tamaño no disponible";
  if (value < 1024) return `${value} B`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
