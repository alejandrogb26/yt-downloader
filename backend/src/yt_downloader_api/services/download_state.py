from yt_downloader_api.db.models import DownloadJobStatus

ALLOWED_TRANSITIONS = {
    DownloadJobStatus.QUEUED.value: {DownloadJobStatus.RUNNING.value},
    DownloadJobStatus.RUNNING.value: {
        DownloadJobStatus.COMPLETED.value,
        DownloadJobStatus.FAILED.value,
    },
}


class InvalidDownloadStateTransitionError(Exception):
    """Raised when a download job state transition is not allowed."""


def validate_status_transition(current_status: str, next_status: str) -> None:
    if next_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
        raise InvalidDownloadStateTransitionError
