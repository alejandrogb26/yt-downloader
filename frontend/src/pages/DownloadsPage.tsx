import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { createDownloadJob, getDownloads, getProfiles } from "../api/client";
import { getUserErrorMessage } from "../api/errors";
import type { DownloadJobListItem, Profile } from "../api/types";
import { useSelection } from "../app/SelectionContext";
import { ProfileSelect } from "../components/ProfileSelect";
import { StatusMessage } from "../components/StatusMessage";
import { Card, EmptyState, Field, SelectControl, Skeleton, TextInput } from "../components/ui";
import {
  formatProgress,
  getStatusIcon,
  getStatusLabel,
  getStatusTone,
  shouldPoll,
} from "../features/downloads/status";
import { displayPath } from "../features/library/path";

type JobScope = "profile" | "all";

export function DownloadsPage() {
  const queryClient = useQueryClient();
  const { selectedProfileId, setSelectedProfileId, destinationPath } = useSelection();
  const [sourceUrl, setSourceUrl] = useState("");
  const [requestedFilename, setRequestedFilename] = useState("");
  const [filenameError, setFilenameError] = useState("");
  const [jobScope, setJobScope] = useState<JobScope>("profile");
  const [successMessage, setSuccessMessage] = useState("");

  const profilesQuery = useQuery({ queryKey: ["profiles"], queryFn: getProfiles });
  const profiles = useMemo(() => profilesQuery.data?.profiles ?? [], [profilesQuery.data]);

  useEffect(() => {
    if (!selectedProfileId && profiles.length > 0) {
      setSelectedProfileId(profiles[0].id);
    }
  }, [profiles, selectedProfileId, setSelectedProfileId]);

  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId);
  const downloadsProfileId = jobScope === "profile" ? selectedProfileId : undefined;
  const downloadsQuery = useQuery({
    queryKey: ["downloads", downloadsProfileId ?? "all"],
    queryFn: () => getDownloads(downloadsProfileId),
    enabled: jobScope === "all" || Boolean(selectedProfileId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return shouldPoll(items.map((item) => item.status)) ? 5_000 : false;
    },
  });

  const createMutation = useMutation({
    mutationFn: createDownloadJob,
    onSuccess: () => {
      setSuccessMessage("Trabajo de descarga creado correctamente.");
      setSourceUrl("");
      setRequestedFilename("");
      setFilenameError("");
      void queryClient.invalidateQueries({ queryKey: ["downloads"] });
    },
  });

  const canCreate = Boolean(selectedProfileId && sourceUrl.trim()) && profiles.length > 0;
  const selectLibraryLink = `/library?profile=${encodeURIComponent(selectedProfileId)}&select=1`;
  const jobs = downloadsQuery.data?.items ?? [];

  return (
    <div className="downloads-page">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Cola de audio</p>
          <h2>Nueva descarga y seguimiento</h2>
          <p>
            Añade enlaces de YouTube a la cola, elige una carpeta destino y revisa el estado
            de los últimos trabajos sin salir de la pantalla.
          </p>
        </div>
        <div className="hero-profile">
          <ProfileSelect
            profiles={profiles}
            value={selectedProfileId}
            onChange={setSelectedProfileId}
            disabled={profilesQuery.isLoading}
          />
        </div>
      </section>

      {profilesQuery.isError ? (
        <StatusMessage tone="error">{getUserErrorMessage(profilesQuery.error)}</StatusMessage>
      ) : null}
      {!profilesQuery.isLoading && profiles.length === 0 ? (
        <StatusMessage tone="info">No hay perfiles disponibles. No se pueden crear trabajos.</StatusMessage>
      ) : null}

      <div className="downloads-grid">
        <Card className="new-download-card" aria-labelledby="new-download-heading">
          <div className="card-heading">
            <div>
              <h2 id="new-download-heading">Nueva descarga</h2>
              <p>URL, perfil y destino antes de enviar a la cola.</p>
            </div>
            <span className="action-dot" aria-hidden="true">●</span>
          </div>

          {profilesQuery.isLoading ? <Skeleton label="Cargando perfiles" /> : null}

          <form
            className="download-form"
            onSubmit={(event) => {
              event.preventDefault();
              setSuccessMessage("");
              const filenameValidationError = validateRequestedFilename(requestedFilename);
              if (filenameValidationError) {
                setFilenameError(filenameValidationError);
                return;
              }
              setFilenameError("");
              const trimmedFilename = requestedFilename.trim().replace(/\s+/g, " ");
              createMutation.mutate({
                profile_id: selectedProfileId,
                source_url: sourceUrl.trim(),
                destination_path: destinationPath,
                requested_filename: trimmedFilename || null,
              });
            }}
          >
            <Field label="URL" hint="Acepta URLs de vídeo de YouTube compatibles con el backend.">
              <TextInput
                value={sourceUrl}
                onChange={(event) => setSourceUrl(event.target.value)}
                placeholder="https://www.youtube.com/watch?v=VIDEO_ID"
                inputMode="url"
              />
            </Field>

            <Field
              label="Nombre del archivo"
              hint="Opcional. No indiques la extensión: se conservará automáticamente el formato de audio disponible."
            >
              <TextInput
                value={requestedFilename}
                onChange={(event) => {
                  setRequestedFilename(event.target.value);
                  if (filenameError) {
                    setFilenameError(validateRequestedFilename(event.target.value));
                  }
                }}
                placeholder="Ej. Sandunga verano"
                aria-invalid={Boolean(filenameError)}
                aria-describedby={filenameError ? "requested-filename-error" : undefined}
              />
            </Field>
            {filenameError ? (
              <p className="field-error" id="requested-filename-error" role="alert">
                {filenameError}
              </p>
            ) : null}

            <div className="destination-card" aria-live="polite">
              <span>Destino seleccionado</span>
              <strong>{displayPath(destinationPath)}</strong>
              <small>{selectedProfile?.display_name ?? "Sin perfil seleccionado"}</small>
              <Link className="button button--secondary" to={selectLibraryLink}>
                Elegir carpeta en biblioteca
              </Link>
            </div>

            <button
              className="button button--primary button--wide"
              type="submit"
              disabled={!canCreate || createMutation.isPending}
            >
              {createMutation.isPending ? "Añadiendo..." : "Añadir a la cola"}
            </button>
          </form>

          {successMessage ? <StatusMessage tone="success">{successMessage}</StatusMessage> : null}
          {createMutation.isError ? (
            <StatusMessage tone="error">{getUserErrorMessage(createMutation.error)}</StatusMessage>
          ) : null}
        </Card>

        <Card className="jobs-card" aria-labelledby="downloads-heading">
          <div className="list-toolbar">
            <div>
              <h2 id="downloads-heading">Trabajos recientes</h2>
              <p>{downloadsQuery.data?.total ?? jobs.length} trabajos visibles</p>
            </div>
            <label className="inline-field">
              <span>Mostrar</span>
              <SelectControl value={jobScope} onChange={(event) => setJobScope(event.target.value as JobScope)}>
                <option value="profile">Perfil actual</option>
                <option value="all">Todos los perfiles</option>
              </SelectControl>
            </label>
          </div>

          {downloadsQuery.isLoading ? <Skeleton label="Cargando trabajos" /> : null}
          {downloadsQuery.isError ? (
            <StatusMessage tone="error">{getUserErrorMessage(downloadsQuery.error)}</StatusMessage>
          ) : null}
          {!downloadsQuery.isLoading && jobs.length === 0 ? (
            <EmptyState title="No hay descargas todavía">
              Crea un trabajo nuevo para empezar a poblar la cola de este perfil.
            </EmptyState>
          ) : null}
          {jobs.length > 0 ? <DownloadsList jobs={jobs} profiles={profiles} /> : null}
        </Card>
      </div>
    </div>
  );
}

function DownloadsList({ jobs, profiles }: { jobs: DownloadJobListItem[]; profiles: Profile[] }) {
  const profileNames = useMemo(
    () => new Map(profiles.map((profile) => [profile.id, profile.display_name])),
    [profiles],
  );

  return (
    <div className="downloads-table" role="table" aria-label="Trabajos de descarga">
      <div className="downloads-row downloads-row--head" role="row">
        <span role="columnheader">Estado</span>
        <span role="columnheader">Trabajo</span>
        <span role="columnheader">Destino</span>
        <span role="columnheader">Formato</span>
        <span role="columnheader">Tiempo</span>
        <span role="columnheader">Resultado</span>
      </div>
      {jobs.map((job) => (
        <article className="downloads-row" role="row" key={job.id}>
          <div className="job-status-cell" role="cell">
            <StatusPill job={job} />
            <ProgressBar progress={job.progress_percent} />
          </div>
          <div className="job-main" role="cell">
            <strong>{job.title ?? truncateSource(job.source_url)}</strong>
            {job.requested_filename ? <em>Nombre solicitado: {job.requested_filename}</em> : null}
            <span>{profileNames.get(job.profile_id) ?? job.profile_id}</span>
          </div>
          <div role="cell" data-label="Destino">
            {displayPath(job.destination_path)}
          </div>
          <div role="cell" data-label="Formato">
            <span className="muted">No disponible en listado</span>
          </div>
          <div role="cell" data-label="Tiempo">
            {formatJobTime(job)}
          </div>
          <div role="cell" data-label="Resultado">
            {job.output_path ? displayPath(job.output_path) : <span className="muted">Pendiente</span>}
          </div>
        </article>
      ))}
    </div>
  );
}

function StatusPill({ job }: { job: DownloadJobListItem }) {
  const tone = getStatusTone(job.status);
  return (
    <span className={`status-pill status-pill--${tone}`}>
      <span aria-hidden="true">{getStatusIcon(job.status)}</span>
      {getStatusLabel(job.status)}
      <span className="sr-only">, progreso {formatProgress(job.progress_percent)}</span>
    </span>
  );
}

function ProgressBar({ progress }: { progress: number | null }) {
  const value = progress ?? 0;
  return (
    <div className="progress-wrap">
      <div
        className={progress === null ? "progress progress--unknown" : "progress"}
        aria-hidden="true"
      >
        <span style={{ width: `${Math.max(0, Math.min(value, 100))}%` }} />
      </div>
      <small>{formatProgress(progress)}</small>
    </div>
  );
}

function truncateSource(sourceUrl: string): string {
  return sourceUrl.length > 62 ? `${sourceUrl.slice(0, 59)}...` : sourceUrl;
}

function formatJobTime(job: DownloadJobListItem): string {
  if (job.finished_at) {
    return `Terminó ${formatDate(job.finished_at)}`;
  }
  if (job.started_at) {
    return `Empezó ${formatDate(job.started_at)}`;
  }
  return `Creado ${formatDate(job.created_at)}`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("es", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function validateRequestedFilename(value: string): string {
  const cleaned = value.trim().replace(/\s+/g, " ");
  if (!cleaned) {
    return "";
  }
  if (cleaned.length > 180) {
    return "El nombre del archivo no puede superar 180 caracteres.";
  }
  if (cleaned === "." || cleaned === ".." || cleaned.startsWith(".")) {
    return "El nombre del archivo no puede ser oculto ni reservado.";
  }
  if (
    cleaned.includes("/") ||
    cleaned.includes("\\") ||
    Array.from(cleaned).some((character) => {
      const codePoint = character.codePointAt(0) ?? 0;
      return codePoint < 32 || codePoint === 127;
    })
  ) {
    return "El nombre del archivo no puede contener rutas ni caracteres de control.";
  }
  if (/\.(m4a|mp4|webm|opus|ogg|mp3|flac|aac)$/iu.test(cleaned)) {
    return "No incluyas la extensión del archivo; el sistema la determina automáticamente.";
  }
  return "";
}
