from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class UserRecord:
    user_id: str
    email: str
    password_hash: str
    created_at: datetime


@dataclass
class RefreshTokenRecord:
    token_id: str
    user_id: str
    org_id: str | None
    expires_at: datetime
    revoked: bool = False


class UserRepository(Protocol):
    def create_user(self, email: str, password_hash: str) -> UserRecord:
        ...

    def get_user_by_email(self, email: str) -> UserRecord | None:
        ...

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        ...


class RefreshTokenRepository(Protocol):
    def save_token(
        self,
        token_id: str,
        user_id: str,
        org_id: str | None,
        expires_at: datetime,
    ) -> None:
        ...

    def get_token(self, token_id: str) -> RefreshTokenRecord | None:
        ...

    def revoke_token(self, token_id: str) -> None:
        ...
