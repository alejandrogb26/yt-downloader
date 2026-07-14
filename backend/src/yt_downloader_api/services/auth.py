import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yt_downloader_api.core.config import Settings
from yt_downloader_api.db.models import User, UserSession
from yt_downloader_api.services.passwords import hash_password, verify_password


class AuthenticationError(Exception):
    """Raised when user credentials or session are invalid."""


class AuthPersistenceError(Exception):
    """Raised when auth state cannot be read or written."""


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    session: UserSession
    token: str


def normalize_username(username: str) -> str:
    return username.strip().lower()


def create_user(
    session: Session,
    username: str,
    display_name: str,
    password: str,
    is_admin: bool = False,
    enabled: bool = True,
) -> User:
    normalized = normalize_username(username)
    if not normalized:
        raise ValueError("username is required")
    now = datetime.now(UTC)
    user = User(
        id=str(uuid4()),
        username=normalized,
        password_hash=hash_password(password),
        display_name=display_name.strip() or normalized,
        enabled=enabled,
        is_admin=is_admin,
        created_at=now,
        updated_at=now,
        last_login_at=None,
    )
    try:
        session.add(user)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise AuthPersistenceError from exc
    return user


def authenticate_user(session: Session, username: str, password: str) -> User:
    normalized = normalize_username(username)
    try:
        user = session.scalars(select(User).where(User.username == normalized)).first()
    except SQLAlchemyError as exc:
        raise AuthPersistenceError from exc
    if user is None or not user.enabled:
        raise AuthenticationError
    if not verify_password(password, user.password_hash):
        raise AuthenticationError
    return user


def create_user_session(
    session: Session,
    settings: Settings,
    user: User,
    remember_me: bool,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[UserSession, str]:
    now = datetime.now(UTC)
    timeout = (
        settings.session_remember_me_timeout_seconds
        if remember_me
        else settings.session_idle_timeout_seconds
    )
    token = secrets.token_urlsafe(settings.session_token_bytes)
    user_session = UserSession(
        id=str(uuid4()),
        user_id=user.id,
        session_token_hash=hash_session_token(token),
        remember_me=remember_me,
        created_at=now,
        expires_at=now + timedelta(seconds=timeout),
        last_seen_at=now,
        revoked_at=None,
        user_agent=truncate_optional(user_agent, 255),
        ip_address=truncate_optional(ip_address, 64),
    )
    user.last_login_at = now
    user.updated_at = now
    try:
        session.add(user_session)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise AuthPersistenceError from exc
    return user_session, token


def load_authenticated_session(
    session: Session,
    token: str | None,
) -> AuthenticatedSession:
    if not token:
        raise AuthenticationError
    now = datetime.now(UTC)
    token_hash = hash_session_token(token)
    try:
        user_session = session.scalars(
            select(UserSession).where(UserSession.session_token_hash == token_hash)
        ).first()
        if (
            user_session is None
            or user_session.revoked_at is not None
            or ensure_aware_utc(user_session.expires_at) <= now
        ):
            raise AuthenticationError
        user = session.get(User, user_session.user_id)
        if user is None or not user.enabled:
            raise AuthenticationError
        if now - ensure_aware_utc(user_session.last_seen_at) >= timedelta(minutes=5):
            user_session.last_seen_at = now
            session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise AuthPersistenceError from exc
    return AuthenticatedSession(user=user, session=user_session, token=token)


def revoke_session(session: Session, user_session: UserSession) -> None:
    user_session.revoked_at = datetime.now(UTC)
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise AuthPersistenceError from exc


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for_session_token(token: str) -> str:
    return hmac.new(
        token.encode("utf-8"),
        b"yt-downloader-csrf-v1",
        hashlib.sha256,
    ).hexdigest()


def verify_csrf_token(session_token: str, csrf_token: str | None) -> bool:
    if not csrf_token:
        return False
    expected = csrf_token_for_session_token(session_token)
    return hmac.compare_digest(expected, csrf_token)


def truncate_optional(value: str | None, length: int) -> str | None:
    if value is None:
        return None
    return value[:length]


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
