export type Profile = {
  id: string;
  display_name: string;
};

export type ProfilesResponse = {
  profiles: Profile[];
};

export type AuthUser = {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
};

export type AuthResponse = {
  user: AuthUser;
  profiles: Profile[];
  csrf_token: string;
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

export type LibrarySearchResponse = {
  profile: Profile;
  q: string;
  limit: number;
  truncated: boolean;
  results: LibraryEntry[];
};

export type BatchPreviewItem = {
  index: number;
  source_url: string | null;
  requested_filename: string | null;
  destination_path: string | null;
  errors: string[];
};

export type BatchPreviewResponse = {
  valid: boolean;
  default_destination_path: string | null;
  total_items: number;
  items: BatchPreviewItem[];
  errors: string[];
};

export type DownloadBatchSummary = {
  id: string;
  profile_id: string;
  default_destination_path: string;
  total_items: number;
  queued_count: number;
  running_count: number;
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type DownloadBatchListResponse = {
  items: DownloadBatchSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type CreatedDownloadBatchResponse = {
  batch: DownloadBatchSummary;
  jobs: DownloadJobListItem[];
};

export type CreateDirectoryRequest = {
  parent_path: string;
  name: string;
};

export type CreatedDirectory = {
  name: string;
  path: string;
  type: "directory";
};

export type RenameEntryRequest = {
  path: string;
  new_name: string;
};

export type TrashEntryRequest = {
  path: string;
};

export type TrashedEntry = {
  status: string;
  original_path: string;
};

export type MoveEntryRequest = {
  source_path: string;
  target_directory_path: string;
};

export type TrimAudioRequest = {
  source_path: string;
  start: string;
  end: string;
  output_filename?: string | null;
};

export type AudioMetadata = {
  title?: string | null;
  artist?: string | null;
  album?: string | null;
  album_artist?: string | null;
  genre?: string | null;
  date?: string | null;
  track?: string | null;
};

export type UpdateAudioMetadataRequest = {
  source_path: string;
  metadata: AudioMetadata;
};

export type AudioMetadataResponse = {
  path: string;
  metadata: Record<string, string>;
};

export type AudioOperationResponse = {
  path: string;
  name: string;
  operation: "trim" | "metadata";
};

export type DownloadStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type DownloadJobListItem = {
  id: string;
  batch_id: string | null;
  profile_id: string;
  source_url: string;
  destination_path: string;
  requested_filename: string | null;
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
  requested_filename?: string | null;
};

export type BatchRequest = {
  default_destination_path: string;
  items: Array<{
    url: string;
    destination_path?: string;
    requested_filename?: string | null;
  }>;
};

export type CreatedDownloadJob = {
  id: string;
  profile: Profile;
  source_url: string;
  destination_path: string;
  requested_filename: string | null;
  audio_policy: string;
  status: DownloadStatus;
  progress_percent: number | null;
  title: string | null;
  output_path: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};
