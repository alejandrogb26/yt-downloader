from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yt_downloader_api.db.models import DownloadJob, DownloadJobEvent


class DownloadJobRepositoryError(Exception):
    """Raised when download job persistence fails."""


class DownloadJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_queued_job_with_event(
        self,
        job: DownloadJob,
        created_at: datetime,
    ) -> DownloadJob:
        event = DownloadJobEvent(
            job_id=job.id,
            created_at=created_at,
            level="info",
            message="Download job queued.",
            progress_percent=None,
        )
        try:
            self.session.add(job)
            self.session.add(event)
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadJobRepositoryError from exc
        return job

    def list_jobs(
        self,
        limit: int,
        offset: int,
        profile_id: str | None = None,
        status: str | None = None,
    ) -> tuple[list[DownloadJob], int]:
        statement = select(DownloadJob)
        count_statement = select(func.count()).select_from(DownloadJob)
        statement, count_statement = apply_job_filters(
            statement,
            count_statement,
            profile_id,
            status,
        )
        statement = (
            statement.order_by(
                DownloadJob.created_at.desc(),
                DownloadJob.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        try:
            total = self.session.scalar(count_statement) or 0
            jobs = list(self.session.scalars(statement).all())
        except SQLAlchemyError as exc:
            raise DownloadJobRepositoryError from exc
        return jobs, total

    def get_job(self, job_id: str) -> DownloadJob | None:
        try:
            return self.session.get(DownloadJob, job_id)
        except SQLAlchemyError as exc:
            raise DownloadJobRepositoryError from exc

    def list_events(
        self,
        job_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[DownloadJobEvent], int]:
        count_statement = (
            select(func.count())
            .select_from(DownloadJobEvent)
            .where(DownloadJobEvent.job_id == job_id)
        )
        statement = (
            select(DownloadJobEvent)
            .where(DownloadJobEvent.job_id == job_id)
            .order_by(DownloadJobEvent.created_at.asc(), DownloadJobEvent.id.asc())
            .limit(limit)
            .offset(offset)
        )
        try:
            total = self.session.scalar(count_statement) or 0
            events = list(self.session.scalars(statement).all())
        except SQLAlchemyError as exc:
            raise DownloadJobRepositoryError from exc
        return events, total


def apply_job_filters(
    statement: Select[tuple[DownloadJob]],
    count_statement: Select[tuple[int]],
    profile_id: str | None,
    status: str | None,
) -> tuple[Select[tuple[DownloadJob]], Select[tuple[int]]]:
    if profile_id is not None:
        statement = statement.where(DownloadJob.profile_id == profile_id)
        count_statement = count_statement.where(DownloadJob.profile_id == profile_id)
    if status is not None:
        statement = statement.where(DownloadJob.status == status)
        count_statement = count_statement.where(DownloadJob.status == status)
    return statement, count_statement
