from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ProgressHook = Callable[[dict[str, Any]], None]

AUDIO_FORMAT_SELECTOR = "bestaudio[ext=m4a]/bestaudio"


class DownloadAdapterError(Exception):
    """Raised when a download adapter fails safely."""


@dataclass(frozen=True)
class AudioDownloadResult:
    title: str
    video_id: str
    downloaded_file_path: Path
    source_format_id: str | None
    source_container: str | None
    source_audio_codec: str | None
    output_container: str | None
    output_audio_codec: str | None


class AudioDownloader(Protocol):
    def download_audio(
        self,
        source_url: str,
        job_id: str,
        staging_directory: Path,
        progress_hook: ProgressHook,
    ) -> AudioDownloadResult: ...
