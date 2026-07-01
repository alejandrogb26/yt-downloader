export type Profile = {
  id: string;
  display_name: string;
};

export type ProfilesResponse = {
  profiles: Profile[];
};

export type LibraryEntry = {
  name: string;
  path: string;
  type: "directory" | "file";
  size_bytes: number | null;
};

export type LibraryEntriesResponse = {
  profile: Profile;
  path: string;
  entries: LibraryEntry[];
};

export type DownloadStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type DownloadJobListItem = {
  id: string;
  profile_id: string;
  source_url: string;
  destination_path: string;
  audio_policy: string;
  status: DownloadStatus;
  progress_percent: number | null;
  title: string | null;
  output_path: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type DownloadJobListResponse = {
  items: DownloadJobListItem[];
  total: number;
  limit: number;
  offset: number;
};

export type DownloadJobDetail = DownloadJobListItem & {
  source_format_id: string | null;
  source_container: string | null;
  source_audio_codec: string | null;
  output_container: string | null;
  output_audio_codec: string | null;
  transcode_applied: boolean;
  attempt_count: number;
};

export type CreateDownloadRequest = {
  profile_id: string;
  source_url: string;
  destination_path: string;
};

export type CreatedDownloadJob = {
  id: string;
  profile: Profile;
  source_url: string;
  destination_path: string;
  audio_policy: string;
  status: DownloadStatus;
  progress_percent: number | null;
  title: string | null;
  output_path: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};
