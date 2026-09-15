from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from clasificacion_langchain.auth.service import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from clasificacion_langchain.auth.schemas import LoginInput, RegisterInput
from clasificacion_langchain.api.support.presenters import membership_payload

from ..dependencies import get_principal, get_runtime
from ..runtime import RuntimeContainer


class RegisterPayload(BaseModel):
    email: str = Field(min_length=5)
    password: str = Field(min_length=8)


class LoginPayload(BaseModel):
    email: str = Field(min_length=5)
    password: str = Field(min_length=8)


class RefreshPayload(BaseModel):
    refresh_token: str = Field(min_length=12)


class LogoutPayload(BaseModel):
    refresh_token: str = Field(min_length=12)


router = APIRouter(tags=["auth"])


@router.post("/auth/register")
def register(payload: RegisterPayload, request: Request) -> dict[str, object]:
    runtime = get_runtime(request)
    try:
        user = runtime.auth_service.register(
            RegisterInput(email=payload.email, password=payload.password)
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"user_id": user.user_id, "email": user.email}


@router.post("/auth/login")
def login(payload: LoginPayload, request: Request) -> dict[str, object]:
    runtime = get_runtime(request)
    try:
        session = runtime.auth_service.login(
            LoginInput(email=payload.email, password=payload.password)
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    # Forma plana, alineada con platform-api (`/auth/login` en Spring).
    return {
        "user_id": session.user.user_id,
        "email": session.user.email,
        "memberships": membership_payload(session.memberships),
        "tokens": {
            "access_token": session.tokens.access_token,
            "refresh_token": session.tokens.refresh_token,
            "token_type": session.tokens.token_type,
        },
    }


@router.post("/auth/refresh")
def refresh(payload: RefreshPayload, request: Request) -> dict[str, object]:
    runtime = get_runtime(request)
    try:
        tokens = runtime.auth_service.refresh(payload.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": tokens.token_type,
    }


@router.post("/auth/logout")
def logout(payload: LogoutPayload, request: Request) -> dict[str, str]:
    runtime = get_runtime(request)
    try:
        runtime.auth_service.logout(payload.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"status": "ok"}


@router.get("/me")
def me(
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> dict[str, object]:
    try:
        user, memberships = runtime.auth_service.me(principal.user_id)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    # Forma plana, alineada con platform-api (`GET /me` en Spring).
    return {
        "user_id": user.user_id,
        "email": user.email,
        "memberships": membership_payload(memberships),
        "active_org_id": principal.active_org_id,
        "roles": principal.roles,
    }
