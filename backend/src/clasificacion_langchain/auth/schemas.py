from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RegisterInput:
    email: str
    password: str


@dataclass
class LoginInput:
    email: str
    password: str


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@dataclass
class AuthPrincipal:
    user_id: str
    active_org_id: str | None
    roles: list[str]


@dataclass
class AuthUserView:
    user_id: str
    email: str
