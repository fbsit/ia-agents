from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from clasificacion_langchain.auth.repository import (
    RefreshTokenRecord,
    RefreshTokenRepository,
    UserRecord,
    UserRepository,
)
from clasificacion_langchain.tenancy.repository import (
    MembershipRecord,
    MembershipRepository,
    OrganizationRecord,
    OrganizationRepository,
)


@dataclass
class InMemoryIdentityStore(
    UserRepository,
    RefreshTokenRepository,
    OrganizationRepository,
    MembershipRepository,
):
    def __init__(self) -> None:
        self.users_by_id: dict[str, UserRecord] = {}
        self.user_ids_by_email: dict[str, str] = {}
        self.refresh_tokens: dict[str, RefreshTokenRecord] = {}
        self.organizations_by_id: dict[str, OrganizationRecord] = {}
        self.organization_ids_by_company: dict[str, str] = {}
        self.memberships_by_user: dict[str, list[MembershipRecord]] = {}

    def create_user(self, email: str, password_hash: str) -> UserRecord:
        normalized_email = email.strip().lower()
        if normalized_email in self.user_ids_by_email:
            raise ValueError("Email ya existe")

        user_id = uuid4().hex
        user = UserRecord(
            user_id=user_id,
            email=normalized_email,
            password_hash=password_hash,
            created_at=datetime.now(UTC),
        )
        self.users_by_id[user_id] = user
        self.user_ids_by_email[normalized_email] = user_id
        return user

    def get_user_by_email(self, email: str) -> UserRecord | None:
        user_id = self.user_ids_by_email.get(email.strip().lower())
        if user_id is None:
            return None
        return self.users_by_id.get(user_id)

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return self.users_by_id.get(user_id)

    def save_token(
        self,
        token_id: str,
        user_id: str,
        org_id: str | None,
        expires_at: datetime,
    ) -> None:
        self.refresh_tokens[token_id] = RefreshTokenRecord(
            token_id=token_id,
            user_id=user_id,
            org_id=org_id,
            expires_at=expires_at,
            revoked=False,
        )

    def get_token(self, token_id: str) -> RefreshTokenRecord | None:
        token = self.refresh_tokens.get(token_id)
        if token is None:
            return None
        if token.expires_at <= datetime.now(UTC):
            return None
        return token

    def revoke_token(self, token_id: str) -> None:
        token = self.refresh_tokens.get(token_id)
        if token is None:
            return
        token.revoked = True
        self.refresh_tokens[token_id] = token

    def create_organization(self, name: str, company_id: str) -> OrganizationRecord:
        normalized_company = company_id.strip().lower()
        if normalized_company in self.organization_ids_by_company:
            raise ValueError("company_id ya existe")

        org_id = uuid4().hex
        organization = OrganizationRecord(
            org_id=org_id,
            name=name.strip(),
            company_id=normalized_company,
            created_at=datetime.now(UTC),
        )
        self.organizations_by_id[org_id] = organization
        self.organization_ids_by_company[normalized_company] = org_id
        return organization

    def get_organization(self, org_id: str) -> OrganizationRecord | None:
        return self.organizations_by_id.get(org_id)

    def get_organization_by_company_id(self, company_id: str) -> OrganizationRecord | None:
        org_id = self.organization_ids_by_company.get(company_id.strip().lower())
        if org_id is None:
            return None
        return self.organizations_by_id.get(org_id)

    def add_membership(self, user_id: str, org_id: str, role: str) -> MembershipRecord:
        existing = self.memberships_by_user.get(user_id, [])
        for membership in existing:
            if membership.org_id == org_id:
                return membership

        membership = MembershipRecord(
            user_id=user_id,
            org_id=org_id,
            role=role,
            created_at=datetime.now(UTC),
        )
        self.memberships_by_user.setdefault(user_id, []).append(membership)
        return membership

    def list_memberships(self, user_id: str) -> list[MembershipRecord]:
        return list(self.memberships_by_user.get(user_id, []))
