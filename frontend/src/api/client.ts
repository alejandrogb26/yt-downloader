import { ApiError } from "./errors";
import type {
  CreateDownloadRequest,
  CreatedDownloadJob,
  DownloadJobDetail,
  DownloadJobListResponse,
  LibraryEntriesResponse,
  ProfilesResponse,
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

export async function createDownloadJob(
  body: CreateDownloadRequest,
): Promise<CreatedDownloadJob> {
  return requestJson<CreatedDownloadJob>("/downloads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getDownloads(profileId?: string): Promise<DownloadJobListResponse> {
  const params = new URLSearchParams({ limit: "25", offset: "0" });
  if (profileId) {
    params.set("profile_id", profileId);
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
