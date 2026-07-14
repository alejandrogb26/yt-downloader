from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from yt_downloader_api.db.models import DownloadBatch, DownloadJob, DownloadJobEvent


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

    def create_batch_with_jobs_and_events(
        self,
        batch: DownloadBatch,
        jobs: list[DownloadJob],
        created_at: datetime,
    ) -> DownloadBatch:
        try:
            self.session.add(batch)
            for job in jobs:
                self.session.add(job)
                self.session.add(
                    DownloadJobEvent(
                        job_id=job.id,
                        created_at=created_at,
                        level="info",
                        message="Download job queued.",
                        progress_percent=None,
                    )
                )
            self.session.commit()
            self.session.refresh(batch)
            batch.jobs = jobs
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DownloadJobRepositoryError from exc
        return batch

    def list_jobs(
        self,
        limit: int,
        offset: int,
        profile_id: str | None = None,
        status: str | None = None,
        batch_id: str | None = None,
        profile_ids: set[str] | None = None,
    ) -> tuple[list[DownloadJob], int]:
        statement = select(DownloadJob)
        count_statement = select(func.count()).select_from(DownloadJob)
        statement, count_statement = apply_job_filters(
            statement,
            count_statement,
            profile_id,
            status,
            batch_id,
            profile_ids,
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

    def list_batches(
        self,
        profile_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[DownloadBatch], int]:
        statement = (
            select(DownloadBatch)
            .where(DownloadBatch.profile_id == profile_id)
            .options(selectinload(DownloadBatch.jobs))
            .order_by(DownloadBatch.created_at.desc(), DownloadBatch.id.desc())
            .limit(limit)
            .offset(offset)
        )
        count_statement = (
            select(func.count())
            .select_from(DownloadBatch)
            .where(DownloadBatch.profile_id == profile_id)
        )
        try:
            total = self.session.scalar(count_statement) or 0
            batches = list(self.session.scalars(statement).all())
        except SQLAlchemyError as exc:
            raise DownloadJobRepositoryError from exc
        return batches, total

    def get_batch(self, batch_id: str) -> DownloadBatch | None:
        try:
            return self.session.scalars(
                select(DownloadBatch)
                .where(DownloadBatch.id == batch_id)
                .options(selectinload(DownloadBatch.jobs))
            ).first()
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
    batch_id: str | None,
    profile_ids: set[str] | None,
) -> tuple[Select[tuple[DownloadJob]], Select[tuple[int]]]:
    if profile_ids is not None:
        statement = statement.where(DownloadJob.profile_id.in_(profile_ids))
        count_statement = count_statement.where(DownloadJob.profile_id.in_(profile_ids))
    if profile_id is not None:
        statement = statement.where(DownloadJob.profile_id == profile_id)
        count_statement = count_statement.where(DownloadJob.profile_id == profile_id)
    if status is not None:
        statement = statement.where(DownloadJob.status == status)
        count_statement = count_statement.where(DownloadJob.status == status)
    if batch_id is not None:
        statement = statement.where(DownloadJob.batch_id == batch_id)
        count_statement = count_statement.where(DownloadJob.batch_id == batch_id)
    return statement, count_statement
