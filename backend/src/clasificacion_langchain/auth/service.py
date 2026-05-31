from __future__ import annotations

from dataclasses import dataclass

from clasificacion_langchain.auth.passwords import hash_password, verify_password
from clasificacion_langchain.auth.repository import RefreshTokenRepository, UserRepository
from clasificacion_langchain.auth.schemas import AuthUserView, LoginInput, RegisterInput, TokenPair
from clasificacion_langchain.auth.token_service import TokenService
from clasificacion_langchain.tenancy.repository import MembershipRepository


class EmailAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


@dataclass
class AuthSession:
    user: AuthUserView
    memberships: list[dict[str, str]]
    tokens: TokenPair


class AuthService:
    def __init__(
        self,
        user_repository: UserRepository,
        refresh_repository: RefreshTokenRepository,
        membership_repository: MembershipRepository,
        token_service: TokenService,
    ) -> None:
        self.user_repository = user_repository
        self.refresh_repository = refresh_repository
        self.membership_repository = membership_repository
        self.token_service = token_service

    def register(self, payload: RegisterInput) -> AuthUserView:
        email = payload.email.strip().lower()
        if self.user_repository.get_user_by_email(email) is not None:
            raise EmailAlreadyExistsError("El email ya esta registrado")

        password_hash = hash_password(payload.password)
        user = self.user_repository.create_user(email=email, password_hash=password_hash)
        return AuthUserView(user_id=user.user_id, email=user.email)

    def login(self, payload: LoginInput) -> AuthSession:
        email = payload.email.strip().lower()
        user = self.user_repository.get_user_by_email(email)
        if user is None or not verify_password(payload.password, user.password_hash):
            raise InvalidCredentialsError("Credenciales invalidas")

        memberships = self.membership_repository.list_memberships(user.user_id)
        active_org_id = memberships[0].org_id if memberships else None
        roles = sorted({membership.role for membership in memberships})

        tokens = self.token_service.issue_tokens(
            user_id=user.user_id,
            org_id=active_org_id,
            roles=roles,
        )

        refresh_payload = self.token_service.validate_refresh_token(tokens.refresh_token)
        self.refresh_repository.save_token(
            token_id=refresh_payload.token_id,
            user_id=user.user_id,
            org_id=active_org_id,
            expires_at=refresh_payload.expires_at,
        )

        return AuthSession(
            user=AuthUserView(user_id=user.user_id, email=user.email),
            memberships=[
                {"org_id": membership.org_id, "role": membership.role}
                for membership in memberships
            ],
            tokens=tokens,
        )

    def refresh(self, refresh_token: str) -> TokenPair:
        refresh_payload = self.token_service.validate_refresh_token(refresh_token)
        stored = self.refresh_repository.get_token(refresh_payload.token_id)
        if stored is None or stored.revoked:
            raise InvalidRefreshTokenError("Refresh token revocado o desconocido")

        user = self.user_repository.get_user_by_id(refresh_payload.user_id)
        if user is None:
            raise InvalidRefreshTokenError("Usuario invalido para refresh")

        memberships = self.membership_repository.list_memberships(user.user_id)
        roles = sorted({membership.role for membership in memberships})

        new_tokens = self.token_service.issue_tokens(
            user_id=user.user_id,
            org_id=refresh_payload.org_id,
            roles=roles,
        )
        self.refresh_repository.revoke_token(refresh_payload.token_id)

        new_refresh_payload = self.token_service.validate_refresh_token(new_tokens.refresh_token)
        self.refresh_repository.save_token(
            token_id=new_refresh_payload.token_id,
            user_id=user.user_id,
            org_id=refresh_payload.org_id,
            expires_at=new_refresh_payload.expires_at,
        )
        return new_tokens

    def logout(self, refresh_token: str) -> None:
        refresh_payload = self.token_service.validate_refresh_token(refresh_token)
        self.refresh_repository.revoke_token(refresh_payload.token_id)

    def me(self, user_id: str) -> tuple[AuthUserView, list[dict[str, str]]]:
        user = self.user_repository.get_user_by_id(user_id)
        if user is None:
            raise InvalidCredentialsError("Usuario no encontrado")
        memberships = self.membership_repository.list_memberships(user.user_id)
        return (
            AuthUserView(user_id=user.user_id, email=user.email),
            [{"org_id": membership.org_id, "role": membership.role} for membership in memberships],
        )
