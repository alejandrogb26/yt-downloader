import subprocess
import time
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread

import pytest

from yt_downloader_api.core.config import Settings, get_settings
from yt_downloader_api.db.models import DownloadJob, DownloadJobEvent, DownloadJobStatus
from yt_downloader_api.repositories.download_queue import DownloadQueueRepositoryError
from yt_downloader_api.services.download_queue import (
    CompletedDownloadJob,
    DownloadQueuePersistenceError,
    claim_next_queued_job,
    mark_running_job_as_completed,
    mark_running_job_as_failed,
    mark_stale_running_jobs_as_failed,
    touch_job_heartbeat,
    update_running_job_progress,
)
from yt_downloader_api.services.download_state import (
    InvalidDownloadStateTransitionError,
    validate_status_transition,
)
from yt_downloader_api.worker import main as worker_module
from yt_downloader_api.worker.main import diagnose_queue_source, run_once
from yt_downloader_api.worker.main import main as worker_main


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

    def update_running_job_progress(
        self,
        job_id: str,
        worker_id: str,
        progress_percent: int | None,
        updated_at: datetime,
    ) -> bool:
        job = self.get_current_running_job(job_id, worker_id)
        if job is None:
            return False
        job.progress_percent = progress_percent
        job.updated_at = updated_at
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
        if self.get_current_running_job(job_id, worker_id) is None:
            return False
        self.events.append(
            make_event(
                job_id,
                len(self.events) + 1,
                created_at,
                level,
                message,
                progress_percent,
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
        job = self.get_current_running_job(job_id, worker_id)
        if job is None:
            return False
        job.status = DownloadJobStatus.COMPLETED.value
        job.progress_percent = 100
        job.title = completed.title
        job.output_relative_path = completed.output_relative_path
        job.source_format_id = completed.source_format_id
        job.source_container = completed.source_container
        job.source_audio_codec = completed.source_audio_codec
        job.output_container = completed.output_container
        job.output_audio_codec = completed.output_audio_codec
        job.transcode_applied = False
        job.updated_at = completed_at
        job.heartbeat_at = completed_at
        job.finished_at = completed_at
        self.events.append(
            make_event(
                job.id,
                len(self.events) + 1,
                completed_at,
                "info",
                "Download completed.",
                100,
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
        job = self.get_current_running_job(job_id, worker_id)
        if job is None:
            return False
        job.status = DownloadJobStatus.FAILED.value
        job.error_code = error_code
        job.error_message = error_message
        job.updated_at = failed_at
        job.finished_at = failed_at
        self.events.append(
            make_event(
                job.id,
                len(self.events) + 1,
                failed_at,
                "error",
                error_message,
            )
        )
        return True

    def get_current_running_job(
        self,
        job_id: str,
        worker_id: str,
    ) -> DownloadJob | None:
        job = next((item for item in self.jobs if item.id == job_id), None)
        if (
            job is None
            or job.status != DownloadJobStatus.RUNNING.value
            or job.worker_id != worker_id
        ):
            return None
        return job


class FailingStaleRepository(InMemoryDownloadQueueRepository):
    def mark_stale_running_jobs_as_failed(
        self,
        stale_before: datetime,
        failed_at: datetime,
    ) -> int:
        raise DownloadQueueRepositoryError("simulated stale failure")


class FakeWorkerSession:
    def __init__(self, repository: InMemoryDownloadQueueRepository) -> None:
        self.repository = repository

    def __enter__(self) -> FakeWorkerSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, _model: object, job_id: str) -> DownloadJob | None:
        return next((job for job in self.repository.jobs if job.id == job_id), None)

    def rollback(self) -> None:
        return None


class FailingClaimRepository(InMemoryDownloadQueueRepository):
    def mark_stale_running_jobs_as_failed(
        self,
        stale_before: datetime,
        failed_at: datetime,
    ) -> int:
        return 0

    def claim_next_queued_job(
        self,
        worker_id: str,
        claimed_at: datetime,
    ) -> DownloadJob | None:
        raise DownloadQueueRepositoryError("simulated claim failure")


class CountingHeartbeatRepository(InMemoryDownloadQueueRepository):
    def __init__(self) -> None:
        super().__init__()
        self.heartbeat_count = 0
        self.heartbeat_event = Event()

    def touch_job_heartbeat(
        self,
        job_id: str,
        worker_id: str,
        touched_at: datetime,
    ) -> bool:
        touched = super().touch_job_heartbeat(job_id, worker_id, touched_at)
        if touched:
            self.heartbeat_count += 1
            self.heartbeat_event.set()
        return touched


class FailingHeartbeatRepository(CountingHeartbeatRepository):
    def __init__(self, failing_job_id: str) -> None:
        super().__init__()
        self.failing_job_id = failing_job_id

    def touch_job_heartbeat(
        self,
        job_id: str,
        worker_id: str,
        touched_at: datetime,
    ) -> bool:
        if job_id == self.failing_job_id:
            raise DownloadQueueRepositoryError("simulated heartbeat failure")
        return super().touch_job_heartbeat(job_id, worker_id, touched_at)


class FakeDiagnosticSource:
    def __init__(self) -> None:
        self.checked_repository = False

    def check_connection(self) -> None:
        return None

    def has_heartbeat_column(self) -> bool:
        return True

    def count_jobs_by_status(self) -> dict[str, int]:
        return {
            "queued": 2,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }

    def check_repository(self) -> None:
        self.checked_repository = True


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
    progress_percent: int | None = None,
) -> DownloadJobEvent:
    return DownloadJobEvent(
        id=event_id,
        job_id=job_id,
        created_at=created_at,
        level=level,
        message=message,
        progress_percent=progress_percent,
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


def test_marks_running_job_as_completed_with_technical_fields() -> None:
    repository = InMemoryDownloadQueueRepository()
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [make_job(job_id, now, status="running", worker_id="worker-1")]
    completed = CompletedDownloadJob(
        title="Song",
        output_relative_path="Rock/Song [abc].m4a",
        source_format_id="140",
        source_container="m4a",
        source_audio_codec="aac",
        output_container="m4a",
        output_audio_codec="aac",
    )

    assert mark_running_job_as_completed(repository, job_id, "worker-1", completed)

    job = repository.jobs[0]
    assert job.status == "completed"
    assert job.progress_percent == 100
    assert job.title == "Song"
    assert job.output_relative_path == "Rock/Song [abc].m4a"
    assert job.source_format_id == "140"
    assert job.source_container == "m4a"
    assert job.source_audio_codec == "aac"
    assert job.output_container == "m4a"
    assert job.output_audio_codec == "aac"
    assert job.transcode_applied is False
    assert repository.events[-1].message == "Download completed."
    assert repository.events[-1].progress_percent == 100


def test_marks_running_job_as_failed_with_safe_error() -> None:
    repository = InMemoryDownloadQueueRepository()
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [make_job(job_id, now, status="running", worker_id="worker-1")]

    assert mark_running_job_as_failed(
        repository,
        job_id,
        "worker-1",
        "download_failed",
        "Audio download failed.",
    )

    job = repository.jobs[0]
    assert job.status == "failed"
    assert job.error_code == "download_failed"
    assert job.error_message == "Audio download failed."
    assert repository.events[-1].level == "error"
    assert repository.events[-1].message == "Audio download failed."


def test_updates_progress_without_heartbeat_or_events() -> None:
    repository = InMemoryDownloadQueueRepository()
    now = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    job_id = "00000000-0000-4000-8000-000000000001"
    original_heartbeat = now - timedelta(seconds=10)
    repository.jobs = [
        make_job(
            job_id,
            now,
            status="running",
            worker_id="worker-1",
            heartbeat_at=original_heartbeat,
        )
    ]

    assert update_running_job_progress(repository, job_id, "worker-1", 42)

    assert repository.jobs[0].progress_percent == 42
    assert repository.jobs[0].heartbeat_at == original_heartbeat
    assert repository.events == []


def test_worker_run_once_without_jobs(capsys: pytest.CaptureFixture[str]) -> None:
    repository = InMemoryDownloadQueueRepository()
    settings = Settings(database_url="mysql+pymysql://user:pass@host:3306/db")

    exit_code = run_once(settings, repository)

    assert exit_code == 0
    assert "No queued jobs available." in capsys.readouterr().out


def test_worker_heartbeat_interval_must_be_lower_than_stale_timeout() -> None:
    with pytest.raises(ValueError, match="worker_heartbeat_interval_seconds"):
        Settings(
            worker_heartbeat_interval_seconds=10,
            worker_stale_job_timeout_seconds=10,
        )
    with pytest.raises(ValueError, match="worker_heartbeat_interval_seconds"):
        Settings(worker_heartbeat_interval_seconds=0)


def test_worker_logs_exception_when_stale_recovery_fails(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(database_url="mysql+pymysql://user:secret@host:3306/db")

    with pytest.raises(DownloadQueuePersistenceError):
        run_once(settings, FailingStaleRepository())

    assert "operation=recover stale running jobs" in caplog.text
    assert "simulated stale failure" in caplog.text
    assert "mysql+pymysql" not in caplog.text
    assert "secret" not in caplog.text
    assert "secret" not in capsys.readouterr().out


def test_worker_logs_exception_when_claim_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(database_url="mysql+pymysql://user:secret@host:3306/db")

    with pytest.raises(DownloadQueuePersistenceError):
        run_once(settings, FailingClaimRepository())

    assert "operation=claim next queued job" in caplog.text
    assert "simulated claim failure" in caplog.text
    assert "secret" not in caplog.text


def test_worker_run_once_claims_single_job(capsys: pytest.CaptureFixture[str]) -> None:
    repository = InMemoryDownloadQueueRepository()
    settings = Settings(
        database_url="mysql+pymysql://user:pass@host:3306/db",
        worker_id="worker-1",
    )
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [make_job(job_id, datetime(2026, 6, 28, tzinfo=UTC))]

    def complete_job(
        _settings: Settings,
        _repository: InMemoryDownloadQueueRepository,
        _downloader: object,
        job: object,
        worker_id: str,
    ) -> bool:
        assert isinstance(job, DownloadJob)
        return mark_running_job_as_completed(
            repository,
            job.id,
            worker_id,
            CompletedDownloadJob(
                title="Song",
                output_relative_path="Song [id].m4a",
                source_format_id="140",
                source_container="m4a",
                source_audio_codec="aac",
                output_container="m4a",
                output_audio_codec="aac",
            ),
        )

    exit_code = run_once(settings, repository, executor=complete_job)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert job_id in output
    assert "completed" in output
    assert repository.jobs[0].status == "completed"
    assert [event.message for event in repository.events][-2:] == [
        "Download started.",
        "Download completed.",
    ]


def test_worker_run_once_marks_interrupted_job_failed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = InMemoryDownloadQueueRepository()
    settings = Settings(
        database_url="mysql+pymysql://user:pass@host:3306/db",
        worker_id="worker-1",
    )
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [make_job(job_id, datetime(2026, 6, 28, tzinfo=UTC))]

    def interrupt_job(
        _settings: Settings,
        _repository: InMemoryDownloadQueueRepository,
        _downloader: object,
        _job: object,
        _worker_id: str,
    ) -> bool:
        raise KeyboardInterrupt

    exit_code = run_once(settings, repository, executor=interrupt_job)

    assert exit_code == 1
    assert "interrupted" in capsys.readouterr().out
    assert repository.jobs[0].status == "failed"
    assert repository.jobs[0].error_code == "worker_interrupted"


def test_persistent_worker_respects_concurrency_and_continues_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryDownloadQueueRepository()
    job_ids = [f"00000000-0000-4000-8000-00000000000{index}" for index in range(1, 4)]
    repository.jobs = [
        make_job(
            job_id,
            datetime(2026, 6, 28, tzinfo=UTC),
        )
        for job_id in job_ids
    ]
    active_count = 0
    max_active_count = 0
    completed_count = 0
    lock = Lock()
    first_two_started = Event()
    third_started = Event()
    release_jobs = {job_id: Event() for job_id in job_ids}
    worker_module.stop_event.clear()

    def session_factory() -> FakeWorkerSession:
        return FakeWorkerSession(repository)

    def repository_factory(
        session: FakeWorkerSession,
    ) -> InMemoryDownloadQueueRepository:
        return session.repository

    def execute_job(
        _settings: Settings,
        _repository: InMemoryDownloadQueueRepository,
        _downloader: object,
        job: DownloadJob,
        _worker_id: str,
    ) -> bool:
        nonlocal active_count, completed_count, max_active_count
        with lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
            if active_count == 2:
                first_two_started.set()
            if job.id == job_ids[2]:
                third_started.set()
        release_jobs[job.id].wait(timeout=2)
        mark_running_job_as_completed(
            _repository,
            job.id,
            _worker_id,
            CompletedDownloadJob(
                title="Downloaded title",
                output_relative_path=f"{job.id}.m4a",
                source_format_id="140",
                source_container="m4a",
                source_audio_codec="aac",
                output_container="m4a",
                output_audio_codec="aac",
            ),
        )
        time.sleep(0.01)
        with lock:
            active_count -= 1
            completed_count += 1
            if completed_count == 3:
                worker_module.stop_event.set()
        if job.id.endswith("2"):
            raise RuntimeError("simulated worker failure")
        return True

    monkeypatch.setattr(worker_module, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(worker_module, "DownloadQueueRepository", repository_factory)
    monkeypatch.setattr(worker_module, "execute_download_job", execute_job)

    settings = Settings(
        database_url="mysql+pymysql://user:pass@host:3306/db",
        worker_id="worker-1",
        worker_concurrency=2,
        worker_queue_poll_interval_seconds=1,
    )
    result: dict[str, int] = {}
    thread = Thread(
        target=lambda: result.setdefault(
            "exit_code",
            worker_module.run_persistent_worker(settings),
        )
    )
    thread.start()

    assert first_two_started.wait(timeout=2)
    with lock:
        assert max_active_count == 2
    assert len(repository.claimed_ids) == 2
    assert repository.jobs[2].status == DownloadJobStatus.QUEUED.value

    release_jobs[job_ids[0]].set()
    assert third_started.wait(timeout=2)
    assert len(repository.claimed_ids) == 3
    assert repository.jobs[0].status == DownloadJobStatus.COMPLETED.value
    assert repository.jobs[1].status == DownloadJobStatus.RUNNING.value
    assert repository.jobs[2].status == DownloadJobStatus.RUNNING.value

    release_jobs[job_ids[1]].set()
    release_jobs[job_ids[2]].set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert result["exit_code"] == 0
    assert max_active_count <= 2
    assert completed_count == 3
    assert len(repository.claimed_ids) == 3
    worker_module.stop_event.clear()


def test_execute_claimed_job_marks_event_failure_with_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryDownloadQueueRepository()
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [
        make_job(
            job_id,
            datetime(2026, 6, 28, tzinfo=UTC),
            status=DownloadJobStatus.RUNNING.value,
            worker_id="worker-1",
        )
    ]
    sessions: list[FakeWorkerSession] = []

    class FailingEventRepository(InMemoryDownloadQueueRepository):
        def __init__(self, source: InMemoryDownloadQueueRepository) -> None:
            self.jobs = source.jobs
            self.events = source.events
            self.claimed_ids = source.claimed_ids

        def add_running_job_event(
            self,
            job_id: str,
            worker_id: str,
            level: str,
            message: str,
            progress_percent: int | None,
            created_at: datetime,
        ) -> bool:
            raise DownloadQueueRepositoryError("simulated event failure")

    def session_factory() -> FakeWorkerSession:
        session = FakeWorkerSession(repository)
        sessions.append(session)
        return session

    def repository_factory(
        session: FakeWorkerSession,
    ) -> InMemoryDownloadQueueRepository:
        if len(sessions) == 2:
            return FailingEventRepository(session.repository)
        return session.repository

    def execute_job(*_args: object) -> bool:
        raise AssertionError("download execution must not start after event failure")

    monkeypatch.setattr(worker_module, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(worker_module, "DownloadQueueRepository", repository_factory)
    monkeypatch.setattr(worker_module, "execute_download_job", execute_job)

    completed = worker_module.execute_claimed_job(
        Settings(database_url="mysql+pymysql://user:pass@host:3306/db"),
        job_id,
        "worker-1",
    )

    assert completed is False
    assert len(sessions) == 3
    assert repository.jobs[0].status == DownloadJobStatus.FAILED.value
    assert repository.jobs[0].error_code == "worker_event_failed"


def test_active_job_heartbeat_updates_running_job_with_fresh_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = CountingHeartbeatRepository()
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [
        make_job(
            job_id,
            datetime(2026, 6, 28, tzinfo=UTC),
            status=DownloadJobStatus.RUNNING.value,
            worker_id="worker-1",
        )
    ]
    sessions: list[FakeWorkerSession] = []

    def session_factory() -> FakeWorkerSession:
        session = FakeWorkerSession(repository)
        sessions.append(session)
        return session

    monkeypatch.setattr(
        worker_module,
        "DownloadQueueRepository",
        lambda session: session.repository,
    )
    heartbeat = worker_module.ActiveJobHeartbeat(
        session_factory,
        job_id,
        "worker-1",
        0.01,
    )

    heartbeat.start()
    assert repository.heartbeat_event.wait(timeout=1)
    heartbeat.stop()

    assert repository.heartbeat_count >= 1
    assert len(sessions) >= 1
    assert repository.jobs[0].heartbeat_at is not None


def test_active_job_heartbeat_stops_updating_terminal_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = CountingHeartbeatRepository()
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [
        make_job(
            job_id,
            datetime(2026, 6, 28, tzinfo=UTC),
            status=DownloadJobStatus.RUNNING.value,
            worker_id="worker-1",
        )
    ]
    monkeypatch.setattr(
        worker_module,
        "DownloadQueueRepository",
        lambda session: session.repository,
    )
    heartbeat = worker_module.ActiveJobHeartbeat(
        lambda: FakeWorkerSession(repository),
        job_id,
        "worker-1",
        0.01,
    )

    heartbeat.start()
    assert repository.heartbeat_event.wait(timeout=1)
    repository.jobs[0].status = DownloadJobStatus.COMPLETED.value
    terminal_heartbeat = repository.jobs[0].heartbeat_at
    time.sleep(0.03)
    heartbeat.stop()

    assert repository.jobs[0].heartbeat_at == terminal_heartbeat


def test_concurrent_active_job_heartbeats_use_independent_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = CountingHeartbeatRepository()
    job_ids = [
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
    ]
    repository.jobs = [
        make_job(
            job_id,
            datetime(2026, 6, 28, tzinfo=UTC),
            status=DownloadJobStatus.RUNNING.value,
            worker_id="worker-1",
        )
        for job_id in job_ids
    ]
    sessions: list[FakeWorkerSession] = []
    lock = Lock()

    def session_factory() -> FakeWorkerSession:
        session = FakeWorkerSession(repository)
        with lock:
            sessions.append(session)
        return session

    monkeypatch.setattr(
        worker_module,
        "DownloadQueueRepository",
        lambda session: session.repository,
    )
    heartbeats = [
        worker_module.ActiveJobHeartbeat(session_factory, job_id, "worker-1", 0.01)
        for job_id in job_ids
    ]

    for heartbeat in heartbeats:
        heartbeat.start()
    assert repository.heartbeat_event.wait(timeout=1)
    time.sleep(0.03)
    for heartbeat in heartbeats:
        heartbeat.stop()

    assert all(job.heartbeat_at is not None for job in repository.jobs)
    assert len(sessions) >= 2
    assert len({id(session) for session in sessions}) == len(sessions)


def test_heartbeat_failure_does_not_stop_other_active_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_job_id = "00000000-0000-4000-8000-000000000001"
    healthy_job_id = "00000000-0000-4000-8000-000000000002"
    repository = FailingHeartbeatRepository(failing_job_id)
    repository.jobs = [
        make_job(
            failing_job_id,
            datetime(2026, 6, 28, tzinfo=UTC),
            status=DownloadJobStatus.RUNNING.value,
            worker_id="worker-1",
        ),
        make_job(
            healthy_job_id,
            datetime(2026, 6, 28, tzinfo=UTC),
            status=DownloadJobStatus.RUNNING.value,
            worker_id="worker-1",
        ),
    ]
    monkeypatch.setattr(
        worker_module,
        "DownloadQueueRepository",
        lambda session: session.repository,
    )
    failing_heartbeat = worker_module.ActiveJobHeartbeat(
        lambda: FakeWorkerSession(repository),
        failing_job_id,
        "worker-1",
        0.01,
    )
    healthy_heartbeat = worker_module.ActiveJobHeartbeat(
        lambda: FakeWorkerSession(repository),
        healthy_job_id,
        "worker-1",
        0.01,
    )

    failing_heartbeat.start()
    healthy_heartbeat.start()
    assert repository.heartbeat_event.wait(timeout=1)
    failing_heartbeat.stop()
    healthy_heartbeat.stop()

    assert repository.jobs[0].heartbeat_at is None
    assert repository.jobs[1].heartbeat_at is not None


def test_autonomous_heartbeat_prevents_stale_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = CountingHeartbeatRepository()
    job_id = "00000000-0000-4000-8000-000000000001"
    old_heartbeat = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    repository.jobs = [
        make_job(
            job_id,
            old_heartbeat,
            status=DownloadJobStatus.RUNNING.value,
            heartbeat_at=old_heartbeat,
            worker_id="worker-1",
        )
    ]
    monkeypatch.setattr(
        worker_module,
        "DownloadQueueRepository",
        lambda session: session.repository,
    )
    heartbeat = worker_module.ActiveJobHeartbeat(
        lambda: FakeWorkerSession(repository),
        job_id,
        "worker-1",
        0.01,
    )

    heartbeat.start()
    assert repository.heartbeat_event.wait(timeout=1)
    heartbeat.stop()
    recovered = mark_stale_running_jobs_as_failed(
        repository, old_heartbeat + timedelta(seconds=1)
    )

    assert recovered == 0
    assert repository.jobs[0].status == DownloadJobStatus.RUNNING.value


def test_execute_claimed_job_heartbeats_during_long_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = CountingHeartbeatRepository()
    job_id = "00000000-0000-4000-8000-000000000001"
    repository.jobs = [
        make_job(
            job_id,
            datetime(2026, 6, 28, tzinfo=UTC),
            status=DownloadJobStatus.RUNNING.value,
            worker_id="worker-1",
        )
    ]

    def session_factory() -> FakeWorkerSession:
        return FakeWorkerSession(repository)

    def repository_factory(
        session: FakeWorkerSession,
    ) -> InMemoryDownloadQueueRepository:
        return session.repository

    def execute_job(
        _settings: Settings,
        _repository: InMemoryDownloadQueueRepository,
        _downloader: object,
        job: DownloadJob,
        worker_id: str,
    ) -> bool:
        assert repository.heartbeat_event.wait(timeout=2)
        return mark_running_job_as_completed(
            _repository,
            job.id,
            worker_id,
            CompletedDownloadJob(
                title="Downloaded title",
                output_relative_path=f"{job.id}.m4a",
                source_format_id="140",
                source_container="m4a",
                source_audio_codec="aac",
                output_container="m4a",
                output_audio_codec="aac",
            ),
        )

    monkeypatch.setattr(worker_module, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(worker_module, "DownloadQueueRepository", repository_factory)
    monkeypatch.setattr(worker_module, "execute_download_job", execute_job)

    completed = worker_module.execute_claimed_job(
        Settings(
            database_url="mysql+pymysql://user:pass@host:3306/db",
            worker_heartbeat_interval_seconds=1,
            worker_stale_job_timeout_seconds=10,
        ),
        job_id,
        "worker-1",
    )

    assert completed is True
    assert repository.heartbeat_count >= 1
    assert repository.jobs[0].status == DownloadJobStatus.COMPLETED.value


def test_worker_main_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()

    exit_code = worker_main([])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "DATABASE_URL is required" in output
    assert "mysql" not in output


def test_diagnose_queue_without_database_url_is_safe(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = diagnose_queue_source(
        Settings(database_url=None),
        FakeDiagnosticSource(),
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "DATABASE_URL is required" in output
    assert "mysql" not in output


def test_diagnose_queue_success_with_fake_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = FakeDiagnosticSource()
    settings = Settings(database_url="mysql+pymysql://user:secret@host:3306/db")

    exit_code = diagnose_queue_source(settings, source)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Database connection: OK" in output
    assert "Queue schema: OK" in output
    assert "Queued jobs: 2" in output
    assert "Running jobs: 0" in output
    assert "Queue repository check: OK" in output
    assert "read-only" in output
    assert "secret" not in output
    assert source.checked_repository is True


def test_diagnose_queue_does_not_run_external_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_process(*args: object, **kwargs: object) -> None:
        raise AssertionError("External processes must not be executed")

    monkeypatch.setattr(subprocess, "run", fail_process)
    monkeypatch.setattr(subprocess, "Popen", fail_process)

    assert (
        diagnose_queue_source(
            Settings(database_url="mysql+pymysql://user:secret@host:3306/db"),
            FakeDiagnosticSource(),
        )
        == 0
    )


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
