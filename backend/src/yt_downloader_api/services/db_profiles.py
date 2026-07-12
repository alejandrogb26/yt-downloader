from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yt_downloader_api.db.models import LibraryProfileRecord, User, UserProfileAccess
from yt_downloader_api.models.profiles import LibraryProfile


class ProfilePersistenceError(Exception):
    """Raised when library profile state cannot be loaded safely."""


VALID_ACCESS_ROLES = {"owner", "read_write", "read_only"}
OPERATIVE_ACCESS_ROLES = {"owner", "read_write"}


def to_library_profile(record: LibraryProfileRecord) -> LibraryProfile:
    return LibraryProfile(
        id=record.slug,
        display_name=record.display_name,
        root_path=record.root_path,
        enabled=record.enabled,
    )


def list_authorized_profiles(session: Session, user: User) -> list[LibraryProfile]:
    try:
        if user.is_admin:
            records = list(
                session.scalars(
                    select(LibraryProfileRecord)
                    .where(LibraryProfileRecord.enabled.is_(True))
                    .order_by(LibraryProfileRecord.display_name.asc())
                ).all()
            )
        else:
            records = list(
                session.scalars(
                    select(LibraryProfileRecord)
                    .join(
                        UserProfileAccess,
                        UserProfileAccess.profile_id == LibraryProfileRecord.id,
                    )
                    .where(UserProfileAccess.user_id == user.id)
                    .where(LibraryProfileRecord.enabled.is_(True))
                    .order_by(LibraryProfileRecord.display_name.asc())
                ).all()
            )
    except SQLAlchemyError as exc:
        raise ProfilePersistenceError from exc
    return [to_library_profile(record) for record in records]


def get_authorized_profile(
    session: Session,
    user: User,
    profile_slug: str,
    require_write: bool = False,
) -> LibraryProfile | None:
    try:
        statement = select(LibraryProfileRecord).where(
            LibraryProfileRecord.slug == profile_slug,
            LibraryProfileRecord.enabled.is_(True),
        )
        if not user.is_admin:
            statement = statement.join(
                UserProfileAccess,
                UserProfileAccess.profile_id == LibraryProfileRecord.id,
            ).where(UserProfileAccess.user_id == user.id)
            if require_write:
                statement = statement.where(
                    UserProfileAccess.role.in_(OPERATIVE_ACCESS_ROLES)
                )
        record = session.scalars(statement).first()
    except SQLAlchemyError as exc:
        raise ProfilePersistenceError from exc
    return to_library_profile(record) if record is not None else None


def load_enabled_profile(session: Session, profile_slug: str) -> LibraryProfile | None:
    try:
        record = session.scalars(
            select(LibraryProfileRecord).where(
                LibraryProfileRecord.slug == profile_slug,
                LibraryProfileRecord.enabled.is_(True),
            )
        ).first()
    except SQLAlchemyError as exc:
        raise ProfilePersistenceError from exc
    return to_library_profile(record) if record is not None else None


def load_enabled_profiles(session: Session) -> list[LibraryProfile]:
    try:
        records = list(
            session.scalars(
                select(LibraryProfileRecord)
                .where(LibraryProfileRecord.enabled.is_(True))
                .order_by(LibraryProfileRecord.display_name.asc())
            ).all()
        )
    except SQLAlchemyError as exc:
        raise ProfilePersistenceError from exc
    return [to_library_profile(record) for record in records]


def upsert_library_profile(
    session: Session,
    slug: str,
    display_name: str,
    root_path: str,
    enabled: bool,
) -> LibraryProfileRecord:
    if not Path(root_path).is_absolute():
        raise ValueError("root_path must be absolute")
    now = datetime.now(UTC)
    try:
        record = session.scalars(
            select(LibraryProfileRecord).where(LibraryProfileRecord.slug == slug)
        ).first()
        if record is None:
            record = LibraryProfileRecord(
                id=str(uuid4()),
                slug=slug,
                display_name=display_name,
                root_path=root_path,
                enabled=enabled,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.display_name = display_name
            record.root_path = root_path
            record.enabled = enabled
            record.updated_at = now
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise ProfilePersistenceError from exc
    return record


def grant_profile_access(
    session: Session,
    user: User,
    profile: LibraryProfileRecord,
    role: str,
) -> None:
    if role not in VALID_ACCESS_ROLES:
        raise ValueError("invalid profile access role")
    now = datetime.now(UTC)
    try:
        access = session.get(UserProfileAccess, (user.id, profile.id))
        if access is None:
            access = UserProfileAccess(
                user_id=user.id,
                profile_id=profile.id,
                role=role,
                created_at=now,
            )
            session.add(access)
        else:
            access.role = role
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise ProfilePersistenceError from exc
