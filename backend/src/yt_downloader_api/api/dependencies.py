from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yt_downloader_api.core.config import Settings, get_settings
from yt_downloader_api.db.session import DatabaseConfigurationError, get_db_session
from yt_downloader_api.services.auth import (
    AuthenticatedSession,
    AuthenticationError,
    AuthPersistenceError,
    load_authenticated_session,
    verify_csrf_token,
)

AUTH_REQUIRED_MESSAGE = "Authentication required."
CSRF_REQUIRED_MESSAGE = "CSRF token is invalid or missing."


@dataclass(frozen=True)
class AuthContext:
    session: Session
    auth: AuthenticatedSession


def get_database_session() -> Generator[Session]:
    session_generator = get_db_session()
    try:
        yield next(session_generator)
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        ) from exc
    finally:
        session_generator.close()


DatabaseSessionDep = Annotated[Session, Depends(get_database_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_auth_context(
    request: Request,
    session: DatabaseSessionDep,
    settings: SettingsDep,
) -> AuthContext:
    token = request.cookies.get(settings.session_cookie_name)
    try:
        auth = load_authenticated_session(session, token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_REQUIRED_MESSAGE,
        ) from exc
    except AuthPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable.",
        ) from exc
    return AuthContext(session=session, auth=auth)


def require_csrf_token(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    if not verify_csrf_token(context.auth.token, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CSRF_REQUIRED_MESSAGE,
        )
    return context
