import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from yt_downloader_api.core.config import Settings, get_settings
from yt_downloader_api.db.models import DownloadJob, DownloadJobEvent, DownloadJobStatus
from yt_downloader_api.services.download_queue import (
    claim_next_queued_job,
    mark_stale_running_jobs_as_failed,
    touch_job_heartbeat,
)
from yt_downloader_api.services.download_state import (
    InvalidDownloadStateTransitionError,
    validate_status_transition,
)
from yt_downloader_api.worker.main import main as worker_main
from yt_downloader_api.worker.main import run_once


class InMemoryDownloadQueueRepository:
    def __init__(self) -> None:
        self.jobs: list[DownloadJob] = []
        self.events: list[DownloadJobEvent] = []
        self.claimed_ids: set[str] = set()

    def claim_next_queued_job(
        self,
        worker_id: str,
        claimed_at: datetime,
    ) -> DownloadJob | None:
        queued_jobs = [
            job
            for job in self.jobs
            if job.status == DownloadJobStatus.QUEUED.value
            and job.id not in self.claimed_ids
        ]
        if not queued_jobs:
            return None
        job = sorted(queued_jobs, key=lambda item: (item.created_at, item.id))[0]
        self.claimed_ids.add(job.id)
        job.status = DownloadJobStatus.RUNNING.value
        job.worker_id = worker_id
        job.attempt_count += 1
        if job.started_at is None:
            job.started_at = claimed_at
        job.updated_at = claimed_at
        job.heartbeat_at = claimed_at
        self.events.append(
            make_event(
                job.id,
                len(self.events) + 1,
                claimed_at,
                "info",
                "Download job claimed by worker.",
            )
        )
        return job

    def mark_stale_running_jobs_as_failed(
        self,
        stale_before: datetime,
        failed_at: datetime,
    ) -> int:
        count = 0
        for job in self.jobs:
            if job.status != DownloadJobStatus.RUNNING.value:
                continue
            if job.heartbeat_at is not None and job.heartbeat_at >= stale_before:
                continue
            job.status = DownloadJobStatus.FAILED.value
            job.finished_at = failed_at
            job.updated_at = failed_at
            job.error_code = "worker_interrupted"
            job.error_message = "Download worker stopped before completion."
            self.events.append(
                make_event(
                    job.id,
                    len(self.events) + 1,
                    failed_at,
                    "error",
                    "Download worker stopped before completion.",
                )
            )
            count += 1
        return count

    def touch_job_heartbeat(
        self,
        job_id: str,
        worker_id: str,
        touched_at: datetime,
    ) -> bool:
        job = next((item for item in self.jobs if item.id == job_id), None)
        if (
            job is None
            or job.status != DownloadJobStatus.RUNNING.value
            or job.worker_id != worker_id
        ):
            return False
        job.heartbeat_at = touched_at
        job.updated_at = touched_at
        return True


def make_job(
    job_id: str,
    created_at: datetime,
    status: str = DownloadJobStatus.QUEUED.value,
    heartbeat_at: datetime | None = None,
    worker_id: str | None = None,
    attempt_count: int = 0,
    started_at: datetime | None = None,
) -> DownloadJob:
    return DownloadJob(
        id=job_id,
        profile_id="pepe",
        source_url="https://www.youtube.com/watch?v=VIDEO_ID",
        destination_relative_path="",
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
        error_code=None,
        error_message=None,
        worker_id=worker_id,
        attempt_count=attempt_count,
        created_at=created_at,
        updated_at=created_at,
        heartbeat_at=heartbeat_at,
        started_at=started_at,
        finished_at=None,
    )


def make_event(
    job_id: str,
    event_id: int,
    created_at: datetime,
    level: str,
    message: str,
) -> DownloadJobEvent:
    return DownloadJobEvent(
        id=event_id,
        job_id=job_id,
        created_at=created_at,
        level=level,
        message=message,
        progress_percent=None,
    )


def test_claims_oldest_queued_job_with_id_tiebreaker() -> None:
    repository = InMemoryDownloadQueueRepository()
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    selected_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [
        make_job("00000000-0000-4000-8000-000000000003", now),
        make_job(selected_id, now - timedelta(minutes=1)),
        make_job("00000000-0000-4000-8000-000000000002", now - timedelta(minutes=1)),
    ]

    job = claim_next_queued_job(repository, "worker-1")

    assert job is not None
    assert job.id == selected_id
    assert job.status == "running"
    assert job.worker_id == "worker-1"
    assert job.attempt_count == 1
    assert job.started_at is not None
    assert job.updated_at == job.heartbeat_at
    assert repository.events[-1].message == "Download job claimed by worker."


def test_claim_returns_none_without_queued_jobs_and_prevents_double_claim() -> None:
    repository = InMemoryDownloadQueueRepository()
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [make_job(job_id, now)]

    first_job = claim_next_queued_job(repository, "worker-1")
    second_job = claim_next_queued_job(repository, "worker-2")

    assert first_job is not None
    assert first_job.id == job_id
    assert second_job is None
    assert len(repository.events) == 1


def test_claim_preserves_existing_started_at() -> None:
    repository = InMemoryDownloadQueueRepository()
    created_at = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    started_at = created_at - timedelta(minutes=5)
    repository.jobs = [
        make_job(
            "00000000-0000-4000-8000-000000000001",
            created_at,
            started_at=started_at,
        )
    ]

    job = claim_next_queued_job(repository, "worker-1")

    assert job is not None
    assert job.started_at == started_at


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    [
        ("completed", "running"),
        ("cancelled", "running"),
        ("failed", "completed"),
        ("queued", "failed"),
    ],
)
def test_rejects_invalid_state_transitions(
    current_status: str,
    next_status: str,
) -> None:
    with pytest.raises(InvalidDownloadStateTransitionError):
        validate_status_transition(current_status, next_status)


def test_marks_stale_running_jobs_as_failed() -> None:
    repository = InMemoryDownloadQueueRepository()
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    stale_before = now - timedelta(minutes=15)
    stale_job = make_job(
        "00000000-0000-4000-8000-000000000001",
        now,
        status="running",
        heartbeat_at=stale_before - timedelta(seconds=1),
        worker_id="worker-1",
        attempt_count=2,
    )
    null_heartbeat_job = make_job(
        "00000000-0000-4000-8000-000000000002",
        now,
        status="running",
        heartbeat_at=None,
        worker_id="worker-2",
        attempt_count=3,
    )
    fresh_job = make_job(
        "00000000-0000-4000-8000-000000000003",
        now,
        status="running",
        heartbeat_at=now,
    )
    repository.jobs = [
        stale_job,
        null_heartbeat_job,
        fresh_job,
        make_job("00000000-0000-4000-8000-000000000004", now, status="queued"),
        make_job("00000000-0000-4000-8000-000000000005", now, status="completed"),
        make_job("00000000-0000-4000-8000-000000000006", now, status="failed"),
        make_job("00000000-0000-4000-8000-000000000007", now, status="cancelled"),
    ]

    count = mark_stale_running_jobs_as_failed(repository, stale_before)

    assert count == 2
    assert stale_job.status == "failed"
    assert null_heartbeat_job.status == "failed"
    assert stale_job.worker_id == "worker-1"
    assert stale_job.attempt_count == 2
    assert stale_job.error_code == "worker_interrupted"
    assert stale_job.error_message == "Download worker stopped before completion."
    assert stale_job.finished_at is not None
    assert fresh_job.status == "running"
    assert [event.message for event in repository.events] == [
        "Download worker stopped before completion.",
        "Download worker stopped before completion.",
    ]


def test_touch_job_heartbeat_requires_running_job_and_matching_worker() -> None:
    repository = InMemoryDownloadQueueRepository()
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [make_job(job_id, now, status="running", worker_id="worker-1")]

    assert touch_job_heartbeat(repository, job_id, "worker-2") is False
    assert (
        touch_job_heartbeat(
            repository, "00000000-0000-4000-8000-000000000002", "worker-1"
        )
        is False
    )
    assert touch_job_heartbeat(repository, job_id, "worker-1") is True
    assert repository.jobs[0].heartbeat_at is not None
    assert repository.events == []


def test_worker_run_once_without_jobs(capsys: pytest.CaptureFixture[str]) -> None:
    repository = InMemoryDownloadQueueRepository()
    settings = Settings(database_url="mysql+pymysql://user:pass@host:3306/db")

    exit_code = run_once(settings, repository)

    assert exit_code == 0
    assert "No queued jobs available." in capsys.readouterr().out


def test_worker_run_once_claims_single_job(capsys: pytest.CaptureFixture[str]) -> None:
    repository = InMemoryDownloadQueueRepository()
    settings = Settings(
        database_url="mysql+pymysql://user:pass@host:3306/db",
        worker_id="worker-1",
    )
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [make_job(job_id, datetime(2026, 6, 28, tzinfo=UTC))]

    exit_code = run_once(settings, repository)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert job_id in output
    assert "marked as running" in output
    assert repository.jobs[0].status == "running"


def test_worker_main_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()

    exit_code = worker_main()

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "DATABASE_URL is required" in output
    assert "mysql" not in output


def test_worker_does_not_run_external_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_process(*args: object, **kwargs: object) -> None:
        raise AssertionError("External processes must not be executed")

    monkeypatch.setattr(subprocess, "run", fail_process)
    monkeypatch.setattr(subprocess, "Popen", fail_process)
    repository = InMemoryDownloadQueueRepository()
    settings = Settings(database_url="mysql+pymysql://user:pass@host:3306/db")

    assert run_once(settings, repository) == 0
