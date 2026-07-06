import json
import subprocess
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from yt_downloader_api.api.routes.downloads import get_download_job_repository
from yt_downloader_api.core.config import get_settings
from yt_downloader_api.db.models import DownloadBatch, DownloadJob
from yt_downloader_api.main import app
from yt_downloader_api.repositories.download_jobs import DownloadJobRepositoryError


class FakeDownloadJobRepository:
    def __init__(self) -> None:
        self.jobs: list[DownloadJob] = []
        self.batches: list[DownloadBatch] = []
        self.events: list[dict[str, object]] = []
        self.calls = 0
        self.raise_on_create = False

    def create_queued_job_with_event(
        self,
        job: DownloadJob,
        created_at: datetime,
    ) -> DownloadJob:
        self.calls += 1
        if self.raise_on_create:
            raise DownloadJobRepositoryError
        self.jobs.append(job)
        self.events.append(
            {
                "job_id": job.id,
                "created_at": created_at,
                "level": "info",
                "message": "Download job queued.",
                "progress_percent": None,
            }
        )
        return job

    def create_batch_with_jobs_and_events(
        self,
        batch: DownloadBatch,
        jobs: list[DownloadJob],
        created_at: datetime,
    ) -> DownloadBatch:
        self.calls += 1
        if self.raise_on_create:
            raise DownloadJobRepositoryError
        self.batches.append(batch)
        self.jobs.extend(jobs)
        batch.jobs = jobs
        for job in jobs:
            self.events.append(
                {
                    "job_id": job.id,
                    "created_at": created_at,
                    "level": "info",
                    "message": "Download job queued.",
                    "progress_percent": None,
                }
            )
        return batch

    def list_jobs(
        self,
        limit: int,
        offset: int,
        profile_id: str | None = None,
        status: str | None = None,
        batch_id: str | None = None,
    ) -> tuple[list[DownloadJob], int]:
        jobs = self.jobs
        if profile_id is not None:
            jobs = [job for job in jobs if job.profile_id == profile_id]
        if status is not None:
            jobs = [job for job in jobs if job.status == status]
        if batch_id is not None:
            jobs = [job for job in jobs if job.batch_id == batch_id]
        return jobs[offset : offset + limit], len(jobs)

    def list_batches(
        self,
        profile_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[DownloadBatch], int]:
        batches = [batch for batch in self.batches if batch.profile_id == profile_id]
        return batches[offset : offset + limit], len(batches)

    def get_batch(self, batch_id: str) -> DownloadBatch | None:
        return next((batch for batch in self.batches if batch.id == batch_id), None)


@pytest.fixture(autouse=True)
def clear_settings_and_overrides() -> Iterator[None]:
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    yield
    get_settings.cache_clear()
    app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest.fixture
def fake_repository() -> FakeDownloadJobRepository:
    repository = FakeDownloadJobRepository()
    app.dependency_overrides[get_download_job_repository] = lambda: repository
    return repository


def configure_profiles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profiles: list[dict[str, object]],
) -> None:
    config_path = tmp_path / "profiles.json"
    config_path.write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
    monkeypatch.setenv("PROFILES_CONFIG_PATH", str(config_path))
    get_settings.cache_clear()


def profile_config(root_path: Path, enabled: bool = True) -> dict[str, object]:
    return {
        "id": "pepe",
        "display_name": "Pepe",
        "root_path": str(root_path),
        "enabled": enabled,
    }


async def create_download(
    client: httpx.AsyncClient,
    source_url: str = "https://www.youtube.com/watch?v=VIDEO_ID",
    destination_path: str = "",
    profile_id: str = "pepe",
    requested_filename: str | None = None,
) -> httpx.Response:
    payload = {
        "profile_id": profile_id,
        "source_url": source_url,
        "destination_path": destination_path,
    }
    if requested_filename is not None:
        payload["requested_filename"] = requested_filename
    return await client.post(
        "/api/v1/downloads",
        json=payload,
    )


@pytest.mark.anyio
async def test_create_download_job_success(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "Rock" / "Clasicos").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, destination_path="Rock/Clasicos")

    body = response.json()
    job = fake_repository.jobs[0]
    assert response.status_code == 201
    assert UUID(body["id"]).version == 4
    assert body == {
        "id": job.id,
        "profile": {"id": "pepe", "display_name": "Pepe"},
        "source_url": "https://www.youtube.com/watch?v=VIDEO_ID",
        "destination_path": "Rock/Clasicos",
        "requested_filename": None,
        "audio_policy": "prefer_m4a_then_best_source",
        "status": "queued",
        "progress_percent": None,
        "title": None,
        "output_path": None,
        "created_at": body["created_at"],
        "started_at": None,
        "finished_at": None,
    }
    assert body["created_at"].endswith("Z")
    assert job.status == "queued"
    assert job.audio_policy == "prefer_m4a_then_best_source"
    assert job.transcode_applied is False
    assert job.destination_relative_path == "Rock/Clasicos"
    assert job.requested_filename is None
    assert job.progress_percent is None
    assert job.title is None
    assert job.output_relative_path is None
    assert job.source_format_id is None
    assert job.source_container is None
    assert job.source_audio_codec is None
    assert job.output_container is None
    assert job.output_audio_codec is None
    assert job.error_code is None
    assert job.error_message is None
    assert job.worker_id is None
    assert job.attempt_count == 0
    assert job.created_at == job.updated_at
    assert len(fake_repository.events) == 1
    assert fake_repository.events[0] == {
        "job_id": job.id,
        "created_at": job.created_at,
        "level": "info",
        "message": "Download job queued.",
        "progress_percent": None,
    }
    assert fake_repository.calls == 1


@pytest.mark.anyio
async def test_preview_download_batch_validates_without_persisting(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "prueba").mkdir(parents=True)
    (library_root / "Rock" / "Directos").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/download-batches/preview",
        json={
            "default_destination_path": "prueba",
            "items": [
                {
                    "url": "https://youtu.be/VIDEO_ID_1",
                    "requested_filename": "Tema uno",
                },
                {
                    "url": "https://www.youtube.com/watch?v=VIDEO_ID_2&utm=x",
                    "destination_path": "Rock/Directos",
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "default_destination_path": "prueba",
        "total_items": 2,
        "items": [
            {
                "index": 0,
                "source_url": "https://www.youtube.com/watch?v=VIDEO_ID_1",
                "requested_filename": "Tema uno",
                "destination_path": "prueba",
                "errors": [],
            },
            {
                "index": 1,
                "source_url": "https://www.youtube.com/watch?v=VIDEO_ID_2",
                "requested_filename": None,
                "destination_path": "Rock/Directos",
                "errors": [],
            },
        ],
        "errors": [],
    }
    assert fake_repository.jobs == []
    assert fake_repository.batches == []


@pytest.mark.anyio
async def test_create_download_batch_creates_batch_jobs_and_events(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "prueba").mkdir(parents=True)
    (library_root / "Rock" / "Directos").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/download-batches",
        json={
            "default_destination_path": "prueba",
            "items": [
                {"url": "https://youtu.be/VIDEO_ID_1"},
                {
                    "url": "https://youtu.be/VIDEO_ID_2",
                    "destination_path": "Rock/Directos",
                    "requested_filename": "Tema dos",
                },
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["batch"]["total_items"] == 2
    assert body["batch"]["queued_count"] == 2
    assert body["batch"]["status"] == "queued"
    assert len(body["jobs"]) == 2
    assert len(fake_repository.batches) == 1
    assert len(fake_repository.jobs) == 2
    assert len(fake_repository.events) == 2
    assert {job.batch_id for job in fake_repository.jobs} == {
        fake_repository.batches[0].id
    }
    assert fake_repository.jobs[0].destination_relative_path == "prueba"
    assert fake_repository.jobs[1].destination_relative_path == "Rock/Directos"
    assert fake_repository.jobs[1].requested_filename == "Tema dos"


@pytest.mark.anyio
async def test_download_batch_rejects_duplicate_urls_after_canonicalization(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "prueba").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/download-batches/preview",
        json={
            "default_destination_path": "prueba",
            "items": [
                {"url": "https://youtu.be/VIDEO_ID"},
                {"url": "https://www.youtube.com/watch?v=VIDEO_ID&feature=share"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["items"][1]["errors"] == ["URL duplicada con el elemento 1."]
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_download_batch_is_atomic_when_one_item_is_invalid(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "prueba").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/download-batches",
        json={
            "default_destination_path": "prueba",
            "items": [
                {"url": "https://youtu.be/VIDEO_ID_1"},
                {"url": "https://example.com/nope"},
            ],
        },
    )

    assert response.status_code == 422
    assert fake_repository.jobs == []
    assert fake_repository.batches == []
    assert fake_repository.events == []


@pytest.mark.anyio
async def test_download_batch_rejects_101_items(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "prueba").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/profiles/pepe/download-batches/preview",
        json={
            "default_destination_path": "prueba",
            "items": [
                {"url": f"https://youtu.be/VIDEO_{index}"} for index in range(101)
            ],
        },
    )

    assert response.status_code == 422
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_downloads_can_filter_by_batch_id(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    (library_root / "prueba").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])
    create_response = await client.post(
        "/api/v1/profiles/pepe/download-batches",
        json={
            "default_destination_path": "prueba",
            "items": [{"url": "https://youtu.be/VIDEO_ID_1"}],
        },
    )
    batch_id = create_response.json()["batch"]["id"]

    response = await client.get("/api/v1/downloads", params={"batch_id": batch_id})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["batch_id"] == batch_id


@pytest.mark.anyio
async def test_create_download_accepts_requested_filename(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, requested_filename="  Sandunga   verano  ")

    assert response.status_code == 201
    assert response.json()["requested_filename"] == "Sandunga verano"
    assert fake_repository.jobs[0].requested_filename == "Sandunga verano"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "requested_filename",
    ["", "   ", "../tema", r"Rock\tema", "\x00", ".", "..", ".oculto", "a" * 181],
)
async def test_create_download_rejects_invalid_requested_filename(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    requested_filename: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, requested_filename=requested_filename)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid requested filename."}
    assert fake_repository.jobs == []


@pytest.mark.anyio
@pytest.mark.parametrize("requested_filename", ["tema.m4a", "tema.WEBM", "Vol. 2.mp3"])
async def test_create_download_rejects_requested_filename_with_audio_extension(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    requested_filename: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, requested_filename=requested_filename)

    assert response.status_code == 422
    assert response.json() == {
        "detail": (
            "No incluyas la extensión del archivo; "
            "el sistema la determina automáticamente."
        )
    }
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_create_download_accepts_root_destination(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await client.post(
        "/api/v1/downloads",
        json={
            "profile_id": "pepe",
            "source_url": "https://www.youtube.com/watch?v=VIDEO_ID",
        },
    )

    assert response.status_code == 201
    assert response.json()["destination_path"] == ""
    assert fake_repository.jobs[0].destination_relative_path == ""


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("source_url", "canonical_source_url"),
    [
        (
            "https://www.youtube.com/watch?v=VIDEO_ID",
            "https://www.youtube.com/watch?v=VIDEO_ID",
        ),
        (
            "https://youtube.com/shorts/VIDEO_ID",
            "https://www.youtube.com/watch?v=VIDEO_ID",
        ),
        (
            "https://youtu.be/VIDEO_ID",
            "https://www.youtube.com/watch?v=VIDEO_ID",
        ),
        (
            "https://www.youtube.com/watch?v=vLe5gDq0BhE&list=RDvLe5gDq0BhE",
            "https://www.youtube.com/watch?v=vLe5gDq0BhE",
        ),
        (
            "https://youtu.be/vLe5gDq0BhE?list=RDvLe5gDq0BhE",
            "https://www.youtube.com/watch?v=vLe5gDq0BhE",
        ),
        (
            "https://www.youtube.com/shorts/vLe5gDq0BhE?si=tracking&feature=share",
            "https://www.youtube.com/watch?v=vLe5gDq0BhE",
        ),
    ],
)
async def test_create_download_accepts_valid_video_urls(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_url: str,
    canonical_source_url: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, source_url=source_url)

    assert response.status_code == 201
    assert fake_repository.jobs[-1].source_url == canonical_source_url
    assert response.json()["source_url"] == canonical_source_url


@pytest.mark.anyio
@pytest.mark.parametrize(
    "source_url",
    [
        "http://www.youtube.com/watch?v=VIDEO_ID",
        "https://example.com/watch?v=VIDEO_ID",
        "https://user@www.youtube.com/watch?v=VIDEO_ID",
        "https://user:pass@www.youtube.com/watch?v=VIDEO_ID",
        "https://www.youtube.com:8443/watch?v=VIDEO_ID",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?list=PL123",
        "https://www.youtube.com/channel/CHANNEL_ID",
        "https://www.youtube.com/results?search_query=music",
        "https://www.youtube.com/@channel",
        "https://www.youtube.com/watch?v=bad\x00id",
        f"https://www.youtube.com/watch?v={'a' * 2050}",
    ],
)
async def test_create_download_rejects_invalid_source_urls(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_url: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, source_url=source_url)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid source URL."}
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_create_download_returns_404_for_unknown_profile(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, profile_id="manolo")

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_create_download_returns_404_for_disabled_profile(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(
        monkeypatch, tmp_path, [profile_config(library_root, enabled=False)]
    )

    response = await create_download(client)

    assert response.status_code == 404
    assert response.json() == {"detail": "Profile not found."}
    assert fake_repository.jobs == []


@pytest.mark.anyio
@pytest.mark.parametrize("destination_path", ["/tmp", "..", r"Rock\Clasicos"])
async def test_create_download_rejects_invalid_destination_paths(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    destination_path: str,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, destination_path=destination_path)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid directory path."}
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_create_download_returns_404_for_missing_destination(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, destination_path="missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Directory not found."}
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_create_download_returns_422_when_destination_is_file(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "Rock").write_bytes(b"file")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, destination_path="Rock")

    assert response.status_code == 422
    assert response.json() == {"detail": "Requested path is not a directory."}
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_create_download_rejects_destination_symlink_traversal(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    symlink_path = library_root / "linked"
    try:
        symlink_path.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are not available on this platform: {exc}")
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, destination_path="linked")

    assert response.status_code == 404
    assert response.json() == {"detail": "Directory not found."}
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_create_download_returns_503_for_unavailable_profile_storage(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing-library"
    configure_profiles(monkeypatch, tmp_path, [profile_config(missing_root)])

    response = await create_download(client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Profile storage is unavailable."}
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_create_download_returns_503_when_database_url_is_absent(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Download service is unavailable."}


@pytest.mark.anyio
async def test_create_download_returns_503_for_persistence_error(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_repository.raise_on_create = True
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Download service is unavailable."}


@pytest.mark.anyio
async def test_create_download_does_not_run_external_processes(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_process(*args: object, **kwargs: object) -> None:
        raise AssertionError("External processes must not be executed")

    monkeypatch.setattr(subprocess, "run", fail_process)
    monkeypatch.setattr(subprocess, "Popen", fail_process)
    library_root = tmp_path / "library"
    library_root.mkdir()
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client)

    assert response.status_code == 201
    assert len(fake_repository.jobs) == 1


@pytest.mark.anyio
async def test_create_download_response_does_not_expose_sensitive_data(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+pymysql://user:secret@127.0.0.1:3306/db?charset=utf8mb4",
    )
    library_root = tmp_path / "library"
    (library_root / "Rock").mkdir(parents=True)
    configure_profiles(monkeypatch, tmp_path, [profile_config(library_root)])

    response = await create_download(client, destination_path="Rock")

    response_text = response.text
    assert response.status_code == 201
    assert str(library_root) not in response_text
    assert "root_path" not in response_text
    assert "destination_relative_path" not in response_text
    assert "DATABASE_URL" not in response_text
    assert "secret" not in response_text
    assert "mysql+pymysql" not in response_text
