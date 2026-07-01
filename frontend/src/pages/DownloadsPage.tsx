import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { createDownloadJob, getDownloads, getProfiles } from "../api/client";
import { getUserErrorMessage } from "../api/errors";
import type { DownloadJobListItem, Profile } from "../api/types";
import { useSelection } from "../app/SelectionContext";
import { ProfileSelect } from "../components/ProfileSelect";
import { StatusMessage } from "../components/StatusMessage";
import { formatProgress, getStatusLabel, shouldPoll } from "../features/downloads/status";
import { displayPath } from "../features/library/path";

type JobScope = "profile" | "all";

export function DownloadsPage() {
  const queryClient = useQueryClient();
  const { selectedProfileId, setSelectedProfileId, destinationPath } = useSelection();
  const [sourceUrl, setSourceUrl] = useState("");
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
      void queryClient.invalidateQueries({ queryKey: ["downloads"] });
    },
  });

  const canCreate = Boolean(selectedProfileId && sourceUrl.trim()) && profiles.length > 0;
  const selectLibraryLink = `/library?profile=${encodeURIComponent(selectedProfileId)}&select=1`;
  const jobs = downloadsQuery.data?.items ?? [];

  return (
    <div className="page-grid">
      <section className="panel" aria-labelledby="new-download-heading">
        <h2 id="new-download-heading">Nueva descarga</h2>
        {profilesQuery.isLoading ? <p>Cargando perfiles...</p> : null}
        {profilesQuery.isError ? (
          <StatusMessage tone="error">{getUserErrorMessage(profilesQuery.error)}</StatusMessage>
        ) : null}
        {!profilesQuery.isLoading && profiles.length === 0 ? (
          <StatusMessage tone="info">
            No hay perfiles disponibles. No se pueden crear trabajos.
          </StatusMessage>
        ) : null}
        <form
          className="form-stack"
          onSubmit={(event) => {
            event.preventDefault();
            setSuccessMessage("");
            createMutation.mutate({
              profile_id: selectedProfileId,
              source_url: sourceUrl.trim(),
              destination_path: destinationPath,
            });
          }}
        >
          <ProfileSelect
            profiles={profiles}
            value={selectedProfileId}
            onChange={setSelectedProfileId}
          />
          <label className="field">
            <span>URL</span>
            <input
              value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)}
              placeholder="https://www.youtube.com/watch?v=VIDEO_ID"
            />
          </label>
          <div className="selected-destination">
            <p>
              <strong>Perfil:</strong> {selectedProfile?.display_name ?? "Sin perfil"}
            </p>
            <p>
              <strong>Destino:</strong> {displayPath(destinationPath)}
            </p>
            <Link className="button button-secondary" to={selectLibraryLink}>
              Elegir carpeta en biblioteca
            </Link>
          </div>
          <button className="button" type="submit" disabled={!canCreate || createMutation.isPending}>
            Crear trabajo
          </button>
        </form>
        {successMessage ? <StatusMessage tone="success">{successMessage}</StatusMessage> : null}
        {createMutation.isError ? (
          <StatusMessage tone="error">{getUserErrorMessage(createMutation.error)}</StatusMessage>
        ) : null}
      </section>

      <section className="panel panel-wide" aria-labelledby="downloads-heading">
        <div className="panel-heading-row">
          <h2 id="downloads-heading">Trabajos recientes</h2>
          <label className="inline-field">
            <span>Mostrar</span>
            <select value={jobScope} onChange={(event) => setJobScope(event.target.value as JobScope)}>
              <option value="profile">Perfil actual</option>
              <option value="all">Todos los perfiles</option>
            </select>
          </label>
        </div>
        {downloadsQuery.isLoading ? <p>Cargando trabajos...</p> : null}
        {downloadsQuery.isError ? (
          <StatusMessage tone="error">{getUserErrorMessage(downloadsQuery.error)}</StatusMessage>
        ) : null}
        {!downloadsQuery.isLoading && jobs.length === 0 ? <p>No hay trabajos para mostrar.</p> : null}
        {jobs.length > 0 ? <DownloadsTable jobs={jobs} profiles={profiles} /> : null}
      </section>
    </div>
  );
}

function DownloadsTable({ jobs, profiles }: { jobs: DownloadJobListItem[]; profiles: Profile[] }) {
  const profileNames = useMemo(
    () => new Map(profiles.map((profile) => [profile.id, profile.display_name])),
    [profiles],
  );
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Trabajo</th>
            <th scope="col">Perfil</th>
            <th scope="col">Destino</th>
            <th scope="col">Estado</th>
            <th scope="col">Progreso</th>
            <th scope="col">Creado</th>
            <th scope="col">Resultado</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>{job.title ?? truncateSource(job.source_url)}</td>
              <td>{profileNames.get(job.profile_id) ?? job.profile_id}</td>
              <td>{displayPath(job.destination_path)}</td>
              <td>
                <span className={`status-pill status-pill--${job.status}`}>
                  {getStatusLabel(job.status)}
                </span>
              </td>
              <td>{formatProgress(job.progress_percent)}</td>
              <td>{formatDate(job.created_at)}</td>
              <td>{job.output_path ? displayPath(job.output_path) : "Pendiente"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function truncateSource(sourceUrl: string): string {
  return sourceUrl.length > 56 ? `${sourceUrl.slice(0, 53)}...` : sourceUrl;
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
