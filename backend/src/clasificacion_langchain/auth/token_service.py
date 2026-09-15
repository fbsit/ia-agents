from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt

from clasificacion_langchain.auth.schemas import AuthPrincipal, TokenPair


logger = logging.getLogger(__name__)


class AuthTokenError(Exception):
    pass


@dataclass
class RefreshTokenPayload:
    token_id: str
    user_id: str
    org_id: str | None
    expires_at: datetime


class TokenService:
    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_ttl_minutes: int = 15,
        refresh_ttl_days: int = 7,
    ) -> None:
        if not secret_key:
            raise ValueError("AUTH_SECRET_KEY es requerido para auth")

        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_ttl_minutes = access_ttl_minutes
        self.refresh_ttl_days = refresh_ttl_days

    @classmethod
    def from_env(cls) -> "TokenService":
        secret_key = os.getenv("AUTH_SECRET_KEY", "").strip()
        if not secret_key:
            secret_key = "dev-insecure-auth-secret"
            logger.warning("auth_secret_key_missing_using_dev_fallback")
        return cls(
            secret_key=secret_key,
            algorithm=os.getenv("AUTH_TOKEN_ALGORITHM", "HS256"),
            access_ttl_minutes=int(os.getenv("AUTH_ACCESS_TTL_MINUTES", "15")),
            refresh_ttl_days=int(os.getenv("AUTH_REFRESH_TTL_DAYS", "7")),
        )

    def issue_tokens(
        self,
        user_id: str,
        org_id: str | None,
        roles: list[str] | None = None,
    ) -> TokenPair:
        now = datetime.now(UTC)
        active_roles = roles or []

        access_claims: dict[str, Any] = {
            "sub": user_id,
            "type": "access",
            "roles": active_roles,
            "org_id": org_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self.access_ttl_minutes)).timestamp()),
        }

        refresh_token_id = uuid4().hex
        refresh_claims: dict[str, Any] = {
            "sub": user_id,
            "type": "refresh",
            "jti": refresh_token_id,
            "org_id": org_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=self.refresh_ttl_days)).timestamp()),
        }

        return TokenPair(
            access_token=jwt.encode(access_claims, self.secret_key, algorithm=self.algorithm),
            refresh_token=jwt.encode(refresh_claims, self.secret_key, algorithm=self.algorithm),
        )

    def validate_access_token(self, token: str) -> AuthPrincipal:
        claims = self._decode(token)
        if claims.get("type") != "access":
            raise AuthTokenError("Token de acceso invalido")

        user_id = str(claims.get("sub", "")).strip()
        if not user_id:
            raise AuthTokenError("Token sin subject")

        org_id = claims.get("org_id")
        active_org = str(org_id) if org_id else None
        roles_raw = claims.get("roles", [])
        roles = [str(role) for role in roles_raw] if isinstance(roles_raw, list) else []

        return AuthPrincipal(user_id=user_id, active_org_id=active_org, roles=roles)

    def validate_refresh_token(self, token: str) -> RefreshTokenPayload:
        claims = self._decode(token)
        if claims.get("type") != "refresh":
            raise AuthTokenError("Token refresh invalido")

        token_id = str(claims.get("jti", "")).strip()
        user_id = str(claims.get("sub", "")).strip()
        if not token_id or not user_id:
            raise AuthTokenError("Token refresh malformado")

        expires_epoch = claims.get("exp")
        if not isinstance(expires_epoch, int):
            raise AuthTokenError("Token refresh sin expiracion")

        org_id = claims.get("org_id")
        return RefreshTokenPayload(
            token_id=token_id,
            user_id=user_id,
            org_id=str(org_id) if org_id else None,
            expires_at=datetime.fromtimestamp(expires_epoch, tz=UTC),
        )

    def _decode(self, token: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except jwt.InvalidTokenError as exc:
            raise AuthTokenError("Token invalido o expirado") from exc

        if not isinstance(claims, dict):
            raise AuthTokenError("Token malformado")
        return claims
