import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from yt_downloader_api.core.config import Settings
from yt_downloader_api.db.models import DownloadJob, DownloadJobEvent, DownloadJobStatus
from yt_downloader_api.downloaders.base import AudioDownloadResult, DownloadAdapterError
from yt_downloader_api.downloaders.yt_dlp_downloader import (
    DownloadError,
    YtDlpAudioDownloader,
    build_yt_dlp_options,
)
from yt_downloader_api.models.profiles import LibraryProfile
from yt_downloader_api.services.download_execution import (
    ProgressReporter,
    StagingConfigurationError,
    build_requested_download_filename,
    build_safe_download_filename,
    calculate_progress_percent,
    execute_download_job,
    publish_download_to_library,
    validate_staging_root,
)
from yt_downloader_api.services.download_queue import CompletedDownloadJob


class InMemoryDownloadQueueRepository:
    def __init__(self, job: DownloadJob) -> None:
        self.job = job
        self.events: list[DownloadJobEvent] = []
        self.progress_updates: list[int | None] = []

    def update_running_job_progress(
        self,
        job_id: str,
        worker_id: str,
        progress_percent: int | None,
        updated_at: datetime,
    ) -> bool:
        if not self.is_current_job(job_id, worker_id):
            return False
        self.job.progress_percent = progress_percent
        self.job.heartbeat_at = updated_at
        self.job.updated_at = updated_at
        self.progress_updates.append(progress_percent)
        return True

    def add_running_job_event(
        self,
        job_id: str,
        worker_id: str,
        level: str,
        message: str,
        progress_percent: int | None,
        created_at: datetime,
    ) -> bool:
        if not self.is_current_job(job_id, worker_id):
            return False
        self.events.append(
            DownloadJobEvent(
                id=len(self.events) + 1,
                job_id=job_id,
                created_at=created_at,
                level=level,
                message=message,
                progress_percent=progress_percent,
            )
        )
        return True

    def mark_running_job_as_completed(
        self,
        job_id: str,
        worker_id: str,
        completed: CompletedDownloadJob,
        completed_at: datetime,
    ) -> bool:
        if not self.is_current_job(job_id, worker_id):
            return False
        self.job.status = DownloadJobStatus.COMPLETED.value
        self.job.progress_percent = 100
        self.job.title = completed.title
        self.job.output_relative_path = completed.output_relative_path
        self.job.source_format_id = completed.source_format_id
        self.job.source_container = completed.source_container
        self.job.source_audio_codec = completed.source_audio_codec
        self.job.output_container = completed.output_container
        self.job.output_audio_codec = completed.output_audio_codec
        self.job.transcode_applied = False
        self.job.updated_at = completed_at
        self.job.heartbeat_at = completed_at
        self.job.finished_at = completed_at
        self.events.append(
            DownloadJobEvent(
                id=len(self.events) + 1,
                job_id=job_id,
                created_at=completed_at,
                level="info",
                message="Download completed.",
                progress_percent=100,
            )
        )
        return True

    def mark_running_job_as_failed(
        self,
        job_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        failed_at: datetime,
    ) -> bool:
        if not self.is_current_job(job_id, worker_id):
            return False
        self.job.status = DownloadJobStatus.FAILED.value
        self.job.error_code = error_code
        self.job.error_message = error_message
        self.job.updated_at = failed_at
        self.job.finished_at = failed_at
        self.events.append(
            DownloadJobEvent(
                id=len(self.events) + 1,
                job_id=job_id,
                created_at=failed_at,
                level="error",
                message=error_message,
                progress_percent=None,
            )
        )
        return True

    def is_current_job(self, job_id: str, worker_id: str) -> bool:
        return (
            self.job.id == job_id
            and self.job.worker_id == worker_id
            and self.job.status == DownloadJobStatus.RUNNING.value
        )


class FakeDownloader:
    def __init__(self, result: AudioDownloadResult | None = None) -> None:
        self.result = result
        self.staging_directory: Path | None = None

    def download_audio(
        self,
        _source_url: str,
        job_id: str,
        staging_directory: Path,
        progress_hook: Any,
    ) -> AudioDownloadResult:
        self.staging_directory = staging_directory
        staging_directory.mkdir(parents=True)
        path = (
            self.result.downloaded_file_path
            if self.result
            else staging_directory / f"{job_id}.webm"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
        progress_hook(
            {"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100}
        )
        return self.result or AudioDownloadResult(
            title="Canción Única",
            video_id="abc123",
            downloaded_file_path=path,
            source_format_id="251",
            source_container="webm",
            source_audio_codec="opus",
            output_container="webm",
            output_audio_codec="opus",
        )


class FailingDownloader:
    def download_audio(self, *_args: object, **_kwargs: object) -> AudioDownloadResult:
        raise DownloadAdapterError("internal")


def make_job(
    root: Path,
    destination_relative_path: str = "Rock",
    requested_filename: str | None = None,
) -> DownloadJob:
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    return DownloadJob(
        id="00000000-0000-4000-8000-000000000001",
        profile_id="pepe",
        source_url="https://example.invalid/watch?id=secret",
        destination_relative_path=destination_relative_path,
        requested_filename=requested_filename,
        audio_policy="prefer_m4a_then_best_source",
        status="running",
        progress_percent=None,
        title=None,
        output_relative_path=None,
        source_format_id=None,
        source_container=None,
        source_audio_codec=None,
        output_container=None,
        output_audio_codec=None,
        transcode_applied=False,
        error_code=None,
        error_message=None,
        worker_id="worker-1",
        attempt_count=1,
        created_at=now,
        updated_at=now,
        heartbeat_at=now,
        started_at=now,
        finished_at=None,
    )


def write_profiles_config(path: Path, root: Path, enabled: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "pepe",
                        "display_name": "Pepe",
                        "root_path": str(root),
                        "enabled": enabled,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def make_settings(tmp_path: Path, root: Path) -> Settings:
    config_path = tmp_path / "profiles.json"
    write_profiles_config(config_path, root)
    return Settings(
        database_url="mysql+pymysql://user:pass@host:3306/db",
        profiles_config_path=str(config_path),
        download_staging_root=str(tmp_path / "staging"),
    )


def test_yt_dlp_options_preserve_audio_policy_and_disable_playlists() -> None:
    options = build_yt_dlp_options("/tmp/job/%(id)s.%(ext)s", lambda _data: None)

    assert options["format"] == "bestaudio[ext=m4a]/bestaudio"
    assert options["noplaylist"] is True
    assert options["quiet"] is True
    assert options["no_warnings"] is True
    assert options["restrictfilenames"] is False
    assert "postprocessors" not in options


def test_yt_dlp_downloader_uses_uuid_staging_and_real_format_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, Any] = {}
    job_id = "00000000-0000-4000-8000-000000000001"

    class FakeYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            captured_options.update(options)

        def __enter__(self) -> FakeYoutubeDL:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_info(self, _url: str, download: bool) -> dict[str, Any]:
            assert download is True
            path = tmp_path / "staging" / job_id / f"{job_id}.m4a"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"audio")
            return {
                "id": "fJ9rUzIMcZQ",
                "title": "Remote Title / must not be path",
                "ext": "m4a",
                "filepath": str(path),
                "format_id": "140",
                "acodec": "aac",
            }

    monkeypatch.setattr(
        "yt_downloader_api.downloaders.yt_dlp_downloader.YoutubeDL",
        FakeYoutubeDL,
    )

    result = YtDlpAudioDownloader().download_audio(
        "https://example.invalid/watch?v=secret",
        job_id,
        tmp_path / "staging" / job_id,
        lambda _progress: None,
    )

    assert captured_options["outtmpl"].endswith(f"/{job_id}.%(ext)s")
    assert "Remote Title" not in captured_options["outtmpl"]
    assert result.title == "Remote Title / must not be path"
    assert result.video_id == "fJ9rUzIMcZQ"
    assert result.source_format_id == "140"
    assert result.source_container == "m4a"
    assert result.source_audio_codec == "aac"
    assert result.output_container == "m4a"
    assert result.output_audio_codec == "aac"


def test_yt_dlp_downloader_converts_download_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingYoutubeDL:
        def __init__(self, _options: dict[str, Any]) -> None:
            pass

        def __enter__(self) -> FailingYoutubeDL:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_info(self, _url: str, download: bool) -> dict[str, Any]:
            raise DownloadError("internal url and stack")

    monkeypatch.setattr(
        "yt_downloader_api.downloaders.yt_dlp_downloader.YoutubeDL",
        FailingYoutubeDL,
    )

    with pytest.raises(DownloadAdapterError, match="Audio download failed"):
        YtDlpAudioDownloader().download_audio(
            "https://example.invalid/watch?v=secret",
            "00000000-0000-4000-8000-000000000001",
            tmp_path / "staging" / "00000000-0000-4000-8000-000000000001",
            lambda _progress: None,
        )


def test_safe_filename_keeps_unicode_and_removes_unsafe_characters() -> None:
    filename = build_safe_download_filename(" Canción/\x00\nNueva ", "id/\x00", "m4a")

    assert filename == "Canción Nueva [id].m4a"
    assert "/" not in filename
    assert "\x00" not in filename
    assert "\n" not in filename
    assert not filename.startswith(".")


def test_safe_filename_falls_back_to_audio() -> None:
    assert build_safe_download_filename("/\x00\n", "/", "") == "audio [audio].audio"


def test_requested_filename_uses_real_extension_and_no_video_id() -> None:
    assert (
        build_requested_download_filename("Sandunga verano", "webm")
        == "Sandunga verano.webm"
    )


def test_calculates_progress_from_total_bytes_and_estimate() -> None:
    assert (
        calculate_progress_percent({"downloaded_bytes": 50, "total_bytes": 100}) == 50
    )
    assert (
        calculate_progress_percent(
            {"downloaded_bytes": 25, "total_bytes_estimate": 100}
        )
        == 25
    )
    assert calculate_progress_percent({"downloaded_bytes": 25}) is None
    assert (
        calculate_progress_percent({"downloaded_bytes": 200, "total_bytes": 100}) == 100
    )


def test_progress_reporter_limits_writes_and_updates_heartbeat() -> None:
    job = make_job(Path("/tmp"))
    repository = InMemoryDownloadQueueRepository(job)
    times = iter(
        [
            datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 7, 1, 12, 0, 1, tzinfo=UTC),
            datetime(2026, 7, 1, 12, 0, 6, tzinfo=UTC),
        ]
    )
    reporter = ProgressReporter(
        repository, job.id, "worker-1", 5, 10, lambda: next(times)
    )

    reporter({"status": "downloading"})
    reporter({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 100})
    reporter({"status": "downloading"})

    assert repository.progress_updates == [None, 5, None]
    assert job.heartbeat_at is not None
    assert repository.events == []


def test_publish_download_to_library_uses_hidden_temp_and_collision_suffix(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    destination = root / "Rock"
    destination.mkdir(parents=True)
    (destination / "Canción [abc123].webm").write_bytes(b"existing")
    staged = tmp_path / "staging" / "00000000-0000-4000-8000-000000000001"
    staged.mkdir(parents=True)
    source = staged / "00000000-0000-4000-8000-000000000001.webm"
    source.write_bytes(b"audio")
    job = make_job(root)
    result = AudioDownloadResult(
        title="Canción",
        video_id="abc123",
        downloaded_file_path=source,
        source_format_id="251",
        source_container="webm",
        source_audio_codec="opus",
        output_container="webm",
        output_audio_codec="opus",
    )
    profile = LibraryProfile(
        id="pepe",
        display_name="Pepe",
        root_path=str(root),
        enabled=True,
    )

    published = publish_download_to_library(profile, job, result)

    assert published.relative_path == "Rock/Canción [abc123] (1).webm"
    assert (destination / "Canción [abc123] (1).webm").read_bytes() == b"audio"
    assert not (destination / f".{job.id}.part").exists()


def test_publish_download_to_library_uses_requested_filename_and_collision_suffix(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    destination = root / "Rock"
    destination.mkdir(parents=True)
    (destination / "Sandunga verano.m4a").write_bytes(b"existing")
    staged = tmp_path / "staging" / "00000000-0000-4000-8000-000000000001"
    staged.mkdir(parents=True)
    source = staged / "00000000-0000-4000-8000-000000000001.m4a"
    source.write_bytes(b"audio")
    job = make_job(root, requested_filename="Sandunga verano")
    result = AudioDownloadResult(
        title="Remote Title",
        video_id="abc123",
        downloaded_file_path=source,
        source_format_id="140",
        source_container="m4a",
        source_audio_codec="aac",
        output_container="m4a",
        output_audio_codec="aac",
    )
    profile = LibraryProfile(
        id="pepe",
        display_name="Pepe",
        root_path=str(root),
        enabled=True,
    )

    published = publish_download_to_library(profile, job, result)

    assert published.relative_path == "Rock/Sandunga verano (1).m4a"
    assert (destination / "Sandunga verano (1).m4a").read_bytes() == b"audio"


def test_execute_download_job_completes_with_fallback_webm_opus(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "Rock").mkdir(parents=True)
    settings = make_settings(tmp_path, root)
    job = make_job(root)
    repository = InMemoryDownloadQueueRepository(job)
    downloader = FakeDownloader()

    assert execute_download_job(settings, repository, downloader, job, "worker-1")

    assert job.status == "completed"
    assert job.title == "Canción Única"
    assert job.output_relative_path == "Rock/Canción Única [abc123].webm"
    assert job.source_format_id == "251"
    assert job.source_container == "webm"
    assert job.source_audio_codec == "opus"
    assert job.output_container == "webm"
    assert job.output_audio_codec == "opus"
    assert job.transcode_applied is False
    assert [event.message for event in repository.events] == [
        "Audio download finished. Moving file to library.",
        "Download completed.",
    ]
    assert downloader.staging_directory is not None
    assert downloader.staging_directory.name == job.id
    assert not downloader.staging_directory.exists()


def test_execute_download_job_completes_with_m4a_aac(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "Rock").mkdir(parents=True)
    settings = make_settings(tmp_path, root)
    job = make_job(root, requested_filename="Mi canción")
    staging = Path(settings.download_staging_root) / job.id
    path = staging / f"{job.id}.m4a"
    result = AudioDownloadResult(
        title="Song",
        video_id="fJ9rUzIMcZQ",
        downloaded_file_path=path,
        source_format_id="140",
        source_container="m4a",
        source_audio_codec="aac",
        output_container="m4a",
        output_audio_codec="aac",
    )
    repository = InMemoryDownloadQueueRepository(job)

    assert execute_download_job(
        settings, repository, FakeDownloader(result), job, "worker-1"
    )

    assert job.output_relative_path == "Rock/Mi canción.m4a"
    assert job.source_container == "m4a"
    assert job.source_audio_codec == "aac"


def test_execute_download_job_fails_safely_when_downloader_fails(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    (root / "Rock").mkdir(parents=True)
    settings = make_settings(tmp_path, root)
    job = make_job(root)
    repository = InMemoryDownloadQueueRepository(job)

    assert not execute_download_job(
        settings, repository, FailingDownloader(), job, "worker-1"
    )

    assert job.status == "failed"
    assert job.error_code == "download_failed"
    assert job.error_message == "Audio download failed."


def test_execute_download_job_fails_when_profile_disabled(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "Rock").mkdir(parents=True)
    config_path = tmp_path / "profiles.json"
    write_profiles_config(config_path, root, enabled=False)
    settings = Settings(
        database_url="mysql+pymysql://user:pass@host:3306/db",
        profiles_config_path=str(config_path),
        download_staging_root=str(tmp_path / "staging"),
    )
    job = make_job(root)
    repository = InMemoryDownloadQueueRepository(job)

    assert not execute_download_job(
        settings, repository, FakeDownloader(), job, "worker-1"
    )

    assert job.status == "failed"
    assert job.error_code == "destination_unavailable"


def test_execute_download_job_fails_when_destination_removed(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    settings = make_settings(tmp_path, root)
    job = make_job(root)
    repository = InMemoryDownloadQueueRepository(job)

    assert not execute_download_job(
        settings, repository, FakeDownloader(), job, "worker-1"
    )

    assert job.status == "failed"
    assert job.error_code == "destination_unavailable"


def test_execute_download_job_fails_when_destination_is_symlink(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "Rock").symlink_to(outside, target_is_directory=True)
    settings = make_settings(tmp_path, root)
    job = make_job(root)
    repository = InMemoryDownloadQueueRepository(job)

    assert not execute_download_job(
        settings, repository, FakeDownloader(), job, "worker-1"
    )

    assert job.status == "failed"
    assert job.error_code == "destination_unavailable"


def test_rejects_staging_root_inside_profile_library(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    config_path = tmp_path / "profiles.json"
    write_profiles_config(config_path, root)
    settings = Settings(
        profiles_config_path=str(config_path),
        download_staging_root=str(root / "staging"),
    )

    with pytest.raises(StagingConfigurationError):
        validate_staging_root(settings)


def test_settings_reject_relative_staging_root() -> None:
    with pytest.raises(ValueError):
        Settings(download_staging_root="relative/staging")
