from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from yt_downloader_api.api.dependencies import (
    AuthContext,
    get_auth_context,
    get_database_session,
)
from yt_downloader_api.core.config import Settings, get_settings
from yt_downloader_api.services.auth import (
    AuthenticationError,
    AuthPersistenceError,
    authenticate_user,
    create_user_session,
    csrf_token_for_session_token,
    revoke_session,
)
from yt_downloader_api.services.db_profiles import (
    ProfilePersistenceError,
    list_authorized_profiles,
)

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS_MESSAGE = "Usuario o contraseña incorrectos."
AUTH_SERVICE_UNAVAILABLE_MESSAGE = "Authentication service is unavailable."


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


class PublicUser(BaseModel):
    id: str
    username: str
    display_name: str
    is_admin: bool


class PublicProfile(BaseModel):
    id: str
    display_name: str


class AuthResponse(BaseModel):
    user: PublicUser
    profiles: list[PublicProfile]
    csrf_token: str


@router.post("/login", response_model=AuthResponse)
def login(
    request_body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_database_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    try:
        user = authenticate_user(session, request_body.username, request_body.password)
        user_session, token = create_user_session(
            session,
            settings,
            user,
            request_body.remember_me,
            request.headers.get("user-agent"),
            request.client.host if request.client else None,
        )
        profiles = list_authorized_profiles(session, user)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_CREDENTIALS_MESSAGE,
        ) from exc
    except (AuthPersistenceError, ProfilePersistenceError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AUTH_SERVICE_UNAVAILABLE_MESSAGE,
        ) from exc

    max_age = int((user_session.expires_at - user_session.created_at).total_seconds())
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        expires=user_session.expires_at.astimezone(UTC),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )
    return build_auth_response(user, profiles, token)


@router.get("/me", response_model=AuthResponse)
def me(
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthResponse:
    try:
        profiles = list_authorized_profiles(context.session, context.auth.user)
    except ProfilePersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AUTH_SERVICE_UNAVAILABLE_MESSAGE,
        ) from exc
    return build_auth_response(context.auth.user, profiles, context.auth.token)


@router.post("/logout")
def logout(
    response: Response,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    try:
        revoke_session(context.session, context.auth.session)
    except AuthPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AUTH_SERVICE_UNAVAILABLE_MESSAGE,
        ) from exc
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )
    return {"status": "ok"}


def build_auth_response(user, profiles, token: str) -> AuthResponse:
    return AuthResponse(
        user=PublicUser(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
        ),
        profiles=[
            PublicProfile(id=profile.id, display_name=profile.display_name)
            for profile in profiles
        ],
        csrf_token=csrf_token_for_session_token(token),
    )
