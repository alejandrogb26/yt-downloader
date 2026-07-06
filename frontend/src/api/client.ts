import { ApiError } from "./errors";
import type {
  CreateDownloadRequest,
  BatchPreviewResponse,
  BatchRequest,
  CreateDirectoryRequest,
  CreatedDirectory,
  CreatedDownloadBatchResponse,
  CreatedDownloadJob,
  DownloadBatchListResponse,
  DownloadJobDetail,
  DownloadJobListResponse,
  LibraryEntriesResponse,
  LibraryEntry,
  LibrarySearchResponse,
  MoveEntryRequest,
  ProfilesResponse,
  RenameEntryRequest,
  TrashEntryRequest,
  TrashedEntry,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export async function getHealth(): Promise<{ status: string }> {
  return requestJson<{ status: string }>("/health");
}

export async function getProfiles(): Promise<ProfilesResponse> {
  return requestJson<ProfilesResponse>("/profiles");
}

export async function getLibraryEntries(
  profileId: string,
  path: string,
): Promise<LibraryEntriesResponse> {
  const params = new URLSearchParams({ path });
  return requestJson<LibraryEntriesResponse>(
    `/profiles/${encodeURIComponent(profileId)}/entries?${params.toString()}`,
  );
}

export async function searchLibrary(
  profileId: string,
  query: string,
  limit = 50,
  signal?: AbortSignal,
): Promise<LibrarySearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return requestJson<LibrarySearchResponse>(
    `/profiles/${encodeURIComponent(profileId)}/search?${params.toString()}`,
    { signal },
  );
}

export async function createDirectory(
  profileId: string,
  parentPath: string,
  name: string,
): Promise<CreatedDirectory> {
  const body: CreateDirectoryRequest = { parent_path: parentPath, name };
  return requestJson<CreatedDirectory>(`/profiles/${encodeURIComponent(profileId)}/directories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function renameEntry(
  profileId: string,
  path: string,
  newName: string,
): Promise<LibraryEntry> {
  const body: RenameEntryRequest = { path, new_name: newName };
  return requestJson<LibraryEntry>(
    `/profiles/${encodeURIComponent(profileId)}/entries/rename`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function trashEntry(profileId: string, path: string): Promise<TrashedEntry> {
  const body: TrashEntryRequest = { path };
  return requestJson<TrashedEntry>(`/profiles/${encodeURIComponent(profileId)}/entries`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function moveEntry(
  profileId: string,
  sourcePath: string,
  targetDirectoryPath: string,
): Promise<LibraryEntry> {
  const body: MoveEntryRequest = {
    source_path: sourcePath,
    target_directory_path: targetDirectoryPath,
  };
  return requestJson<LibraryEntry>(`/profiles/${encodeURIComponent(profileId)}/entries/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function createDownloadJob(
  body: CreateDownloadRequest,
): Promise<CreatedDownloadJob> {
  return requestJson<CreatedDownloadJob>("/downloads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function previewDownloadBatch(
  profileId: string,
  body: BatchRequest,
): Promise<BatchPreviewResponse> {
  return requestJson<BatchPreviewResponse>(
    `/profiles/${encodeURIComponent(profileId)}/download-batches/preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function createDownloadBatch(
  profileId: string,
  body: BatchRequest,
): Promise<CreatedDownloadBatchResponse> {
  return requestJson<CreatedDownloadBatchResponse>(
    `/profiles/${encodeURIComponent(profileId)}/download-batches`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function getDownloadBatches(profileId: string): Promise<DownloadBatchListResponse> {
  const params = new URLSearchParams({ limit: "10", offset: "0" });
  return requestJson<DownloadBatchListResponse>(
    `/profiles/${encodeURIComponent(profileId)}/download-batches?${params.toString()}`,
  );
}

export async function getDownloads(profileId?: string, batchId?: string): Promise<DownloadJobListResponse> {
  const params = new URLSearchParams({ limit: "25", offset: "0" });
  if (profileId) {
    params.set("profile_id", profileId);
  }
  if (batchId) {
    params.set("batch_id", batchId);
  }
  return requestJson<DownloadJobListResponse>(`/downloads?${params.toString()}`);
}

export async function getDownload(jobId: string): Promise<DownloadJobDetail> {
  return requestJson<DownloadJobDetail>(`/downloads/${encodeURIComponent(jobId)}`);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError("No se pudo contactar con la API.");
  }

  const data: unknown = await readJsonSafely(response);
  if (!response.ok) {
    throw new ApiError(readErrorDetail(data), response.status);
  }
  if (data === null || typeof data !== "object") {
    throw new ApiError("La API devolvió una respuesta inesperada.", response.status);
  }
  return data as T;
}

async function readJsonSafely(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function readErrorDetail(data: unknown): string {
  if (
    data !== null &&
    typeof data === "object" &&
    "detail" in data &&
    typeof data.detail === "string" &&
    data.detail.trim()
  ) {
    return data.detail;
  }
  return "La API no pudo completar la operación.";
}
