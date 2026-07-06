import subprocess
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from yt_downloader_api.api.routes.downloads import get_download_job_repository
from yt_downloader_api.core.config import get_settings
from yt_downloader_api.db.models import DownloadJob, DownloadJobEvent
from yt_downloader_api.main import app
from yt_downloader_api.repositories.download_jobs import DownloadJobRepositoryError


class FakeDownloadJobRepository:
    def __init__(self) -> None:
        self.jobs: list[DownloadJob] = []
        self.events: list[DownloadJobEvent] = []
        self.raise_on_read = False

    def create_queued_job_with_event(
        self,
        job: DownloadJob,
        created_at: datetime,
    ) -> DownloadJob:
        self.jobs.append(job)
        self.events.append(
            make_event(job.id, 1, created_at, "info", "Download job queued.")
        )
        return job

    def list_jobs(
        self,
        limit: int,
        offset: int,
        profile_id: str | None = None,
        status: str | None = None,
        batch_id: str | None = None,
    ) -> tuple[list[DownloadJob], int]:
        if self.raise_on_read:
            raise DownloadJobRepositoryError
        jobs = self.jobs
        if profile_id is not None:
            jobs = [job for job in jobs if job.profile_id == profile_id]
        if status is not None:
            jobs = [job for job in jobs if job.status == status]
        if batch_id is not None:
            jobs = [job for job in jobs if job.batch_id == batch_id]
        jobs = sorted(jobs, key=lambda job: (job.created_at, job.id), reverse=True)
        return jobs[offset : offset + limit], len(jobs)

    def get_job(self, job_id: str) -> DownloadJob | None:
        if self.raise_on_read:
            raise DownloadJobRepositoryError
        return next((job for job in self.jobs if job.id == job_id), None)

    def list_events(
        self,
        job_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[DownloadJobEvent], int]:
        if self.raise_on_read:
            raise DownloadJobRepositoryError
        events = [event for event in self.events if event.job_id == job_id]
        events = sorted(events, key=lambda event: (event.created_at, event.id))
        return events[offset : offset + limit], len(events)


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


def make_job(
    job_id: str,
    created_at: datetime,
    profile_id: str = "pepe",
    status: str = "queued",
    destination_path: str = "Rock",
    requested_filename: str | None = None,
) -> DownloadJob:
    return DownloadJob(
        id=job_id,
        profile_id=profile_id,
        source_url="https://www.youtube.com/watch?v=VIDEO_ID",
        destination_relative_path=destination_path,
        requested_filename=requested_filename,
        audio_policy="prefer_m4a_then_best_source",
        status=status,
        progress_percent=None,
        title=None,
        output_relative_path=None,
        source_format_id=None,
        source_container=None,
        source_audio_codec=None,
        output_container=None,
        output_audio_codec=None,
        transcode_applied=False,
        error_code="internal-error",
        error_message="secret database detail",
        worker_id="worker-1",
        attempt_count=0,
        created_at=created_at,
        updated_at=created_at,
        started_at=None,
        finished_at=None,
    )


def make_event(
    job_id: str,
    event_id: int,
    created_at: datetime,
    level: str = "info",
    message: str = "Download job queued.",
) -> DownloadJobEvent:
    return DownloadJobEvent(
        id=event_id,
        job_id=job_id,
        created_at=created_at,
        level=level,
        message=message,
        progress_percent=None,
    )


@pytest.mark.anyio
async def test_list_downloads_empty(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    response = await client.get("/api/v1/downloads")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 25, "offset": 0}
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_list_downloads_orders_by_created_at_and_id_desc(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    older_id = "00000000-0000-4000-8000-000000000001"
    lower_tie_id = "00000000-0000-4000-8000-000000000002"
    higher_tie_id = "00000000-0000-4000-8000-000000000003"
    fake_repository.jobs = [
        make_job(
            older_id,
            now - timedelta(minutes=1),
            requested_filename="Sandunga verano",
        ),
        make_job(lower_tie_id, now),
        make_job(higher_tie_id, now),
    ]

    response = await client.get("/api/v1/downloads")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        higher_tie_id,
        lower_tie_id,
        older_id,
    ]
    older_item = response.json()["items"][2]
    assert older_item["requested_filename"] == "Sandunga verano"


@pytest.mark.anyio
async def test_list_downloads_filters_by_profile_and_status(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    matching_id = "00000000-0000-4000-8000-000000000001"
    fake_repository.jobs = [
        make_job(matching_id, now, profile_id="pepe", status="queued"),
        make_job("00000000-0000-4000-8000-000000000002", now, profile_id="ana"),
        make_job("00000000-0000-4000-8000-000000000003", now, status="failed"),
    ]

    response = await client.get(
        "/api/v1/downloads",
        params={"profile_id": "pepe", "status": "queued"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [matching_id]
    assert response.json()["total"] == 1


@pytest.mark.anyio
async def test_list_downloads_paginates(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    fake_repository.jobs = [
        make_job(f"00000000-0000-4000-8000-00000000000{index}", now)
        for index in range(1, 4)
    ]

    response = await client.get("/api/v1/downloads", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["total"] == 3
    assert response.json()["limit"] == 1
    assert response.json()["offset"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "unknown"}],
)
async def test_list_downloads_rejects_invalid_query_params(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    params: dict[str, int | str],
) -> None:
    response = await client.get("/api/v1/downloads", params=params)

    assert response.status_code == 422
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_get_download_detail(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    job_id = "00000000-0000-4000-8000-000000000001"
    job = make_job(job_id, now)
    job.source_format_id = "140"
    job.source_container = "m4a"
    job.source_audio_codec = "aac"
    job.output_container = "m4a"
    job.output_audio_codec = "aac"
    fake_repository.jobs = [job]
    job.requested_filename = "Sandunga verano"

    response = await client.get(f"/api/v1/downloads/{job_id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": job_id,
        "batch_id": None,
        "profile_id": "pepe",
        "source_url": "https://www.youtube.com/watch?v=VIDEO_ID",
        "destination_path": "Rock",
        "requested_filename": "Sandunga verano",
        "audio_policy": "prefer_m4a_then_best_source",
        "status": "queued",
        "progress_percent": None,
        "title": None,
        "output_path": None,
        "source_format_id": "140",
        "source_container": "m4a",
        "source_audio_codec": "aac",
        "output_container": "m4a",
        "output_audio_codec": "aac",
        "transcode_applied": False,
        "attempt_count": 0,
        "created_at": "2026-06-28T12:00:00Z",
        "started_at": None,
        "finished_at": None,
    }


@pytest.mark.anyio
async def test_get_download_returns_404_for_missing_job(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    response = await client.get(
        "/api/v1/downloads/00000000-0000-4000-8000-000000000001"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Download job not found."}


@pytest.mark.anyio
async def test_get_download_rejects_invalid_uuid(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    response = await client.get("/api/v1/downloads/not-a-uuid")

    assert response.status_code == 422
    assert fake_repository.jobs == []


@pytest.mark.anyio
async def test_list_download_events_orders_and_paginates(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    job_id = "00000000-0000-4000-8000-000000000001"
    fake_repository.jobs = [make_job(job_id, now)]
    fake_repository.events = [
        make_event(job_id, 2, now, message="Second"),
        make_event(job_id, 1, now, message="First"),
        make_event(job_id, 3, now + timedelta(seconds=1), message="Third"),
    ]

    response = await client.get(
        f"/api/v1/downloads/{job_id}/events",
        params={"limit": 2, "offset": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "created_at": "2026-06-28T12:00:00Z",
                "level": "info",
                "message": "Second",
                "progress_percent": None,
            },
            {
                "created_at": "2026-06-28T12:00:01Z",
                "level": "info",
                "message": "Third",
                "progress_percent": None,
            },
        ],
        "total": 3,
        "limit": 2,
        "offset": 1,
    }


@pytest.mark.anyio
async def test_list_download_events_returns_404_when_job_is_missing(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    response = await client.get(
        "/api/v1/downloads/00000000-0000-4000-8000-000000000001/events"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Download job not found."}


@pytest.mark.anyio
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_list_download_events_rejects_invalid_pagination(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    params: dict[str, int],
) -> None:
    job_id = "00000000-0000-4000-8000-000000000001"
    fake_repository.jobs = [make_job(job_id, datetime(2026, 6, 28, tzinfo=UTC))]

    response = await client.get(f"/api/v1/downloads/{job_id}/events", params=params)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_download_read_responses_do_not_expose_internal_fields(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+pymysql://user:secret@127.0.0.1:3306/db?charset=utf8mb4",
    )
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    job_id = "00000000-0000-4000-8000-000000000001"
    job = make_job(job_id, now, destination_path="relative/path")
    job.output_relative_path = "relative/output.m4a"
    fake_repository.jobs = [job]

    list_response = await client.get("/api/v1/downloads")
    detail_response = await client.get(f"/api/v1/downloads/{job_id}")

    for response_text in (list_response.text, detail_response.text):
        assert "worker_id" not in response_text
        assert "error_code" not in response_text
        assert "error_message" not in response_text
        assert "root_path" not in response_text
        assert "DATABASE_URL" not in response_text
        assert "mysql+pymysql" not in response_text
        assert "secret" not in response_text
        assert "/mnt/" not in response_text


@pytest.mark.anyio
async def test_download_reads_return_503_when_database_url_is_absent(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = await client.get("/api/v1/downloads")

    assert response.status_code == 503
    assert response.json() == {"detail": "Download service is unavailable."}


@pytest.mark.anyio
async def test_download_reads_return_503_for_repository_error(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
) -> None:
    fake_repository.raise_on_read = True

    response = await client.get("/api/v1/downloads")

    assert response.status_code == 503
    assert response.json() == {"detail": "Download service is unavailable."}


@pytest.mark.anyio
async def test_download_reads_do_not_run_external_processes(
    client: httpx.AsyncClient,
    fake_repository: FakeDownloadJobRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_process(*args: object, **kwargs: object) -> None:
        raise AssertionError("External processes must not be executed")

    monkeypatch.setattr(subprocess, "run", fail_process)
    monkeypatch.setattr(subprocess, "Popen", fail_process)
    fake_repository.jobs = [
        make_job(
            "00000000-0000-4000-8000-000000000001",
            datetime(2026, 6, 28, tzinfo=UTC),
        )
    ]

    response = await client.get("/api/v1/downloads")

    assert response.status_code == 200
