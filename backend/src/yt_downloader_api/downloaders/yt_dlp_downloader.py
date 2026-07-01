from pathlib import Path
from typing import Any

from yt_dlp import DownloadError, YoutubeDL

from yt_downloader_api.downloaders.base import (
    AUDIO_FORMAT_SELECTOR,
    AudioDownloadResult,
    DownloadAdapterError,
    ProgressHook,
)


class YtDlpAudioDownloader:
    def download_audio(
        self,
        source_url: str,
        job_id: str,
        staging_directory: Path,
        progress_hook: ProgressHook,
    ) -> AudioDownloadResult:
        staging_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        output_template = str(staging_directory / f"{job_id}.%(ext)s")
        options: dict[str, Any] = build_yt_dlp_options(output_template, progress_hook)

        try:
            with YoutubeDL(options) as youtube_dl:
                info = youtube_dl.extract_info(source_url, download=True)
        except DownloadError as exc:
            raise DownloadAdapterError("Audio download failed.") from exc
        except OSError as exc:
            raise DownloadAdapterError("Audio download failed.") from exc

        if not isinstance(info, dict):
            raise DownloadAdapterError("Audio download failed.")

        downloaded_file_path = resolve_downloaded_file_path(info, staging_directory)
        selected_format = get_selected_format(info)
        extension = get_text(info.get("ext")) or get_text(selected_format.get("ext"))
        container = extension or get_text(selected_format.get("container"))
        audio_codec = get_text(selected_format.get("acodec"))

        return AudioDownloadResult(
            title=get_text(info.get("title")) or "audio",
            video_id=get_text(info.get("id")) or job_id,
            downloaded_file_path=downloaded_file_path,
            source_format_id=get_text(selected_format.get("format_id")),
            source_container=container,
            source_audio_codec=audio_codec,
            output_container=container,
            output_audio_codec=audio_codec,
        )


def build_yt_dlp_options(
    output_template: str,
    progress_hook: ProgressHook,
) -> dict[str, Any]:
    return {
        "format": AUDIO_FORMAT_SELECTOR,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": False,
        "outtmpl": output_template,
        "progress_hooks": [progress_hook],
    }


def resolve_downloaded_file_path(info: dict[str, Any], staging_directory: Path) -> Path:
    candidate = get_text(info.get("filepath")) or get_text(info.get("_filename"))
    if candidate is None:
        requested_downloads = info.get("requested_downloads")
        if isinstance(requested_downloads, list) and requested_downloads:
            first_download = requested_downloads[0]
            if isinstance(first_download, dict):
                candidate = get_text(first_download.get("filepath"))
    if candidate is None:
        raise DownloadAdapterError("Audio download failed.")

    path = Path(candidate)
    try:
        path.resolve(strict=False).relative_to(staging_directory.resolve(strict=False))
    except ValueError as exc:
        raise DownloadAdapterError("Audio download failed.") from exc
    return path


def get_selected_format(info: dict[str, Any]) -> dict[str, Any]:
    requested_formats = info.get("requested_formats")
    if isinstance(requested_formats, list) and requested_formats:
        selected = requested_formats[0]
        if isinstance(selected, dict):
            return selected

    requested_downloads = info.get("requested_downloads")
    if isinstance(requested_downloads, list) and requested_downloads:
        selected = requested_downloads[0]
        if isinstance(selected, dict):
            return selected

    return info


def get_text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
