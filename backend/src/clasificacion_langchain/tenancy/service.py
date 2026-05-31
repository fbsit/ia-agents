from __future__ import annotations

import re

from clasificacion_langchain.auth.schemas import AuthPrincipal
from clasificacion_langchain.tenancy.repository import (
    MembershipRecord,
    MembershipRepository,
    OrganizationRecord,
    OrganizationRepository,
)


class TenantContextError(Exception):
    pass


class TenantForbiddenError(Exception):
    pass


def _to_company_slug(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "company"


class TenancyService:
    def __init__(
        self,
        organization_repository: OrganizationRepository,
        membership_repository: MembershipRepository,
    ) -> None:
        self.organization_repository = organization_repository
        self.membership_repository = membership_repository

    def onboard_organization(
        self,
        user_id: str,
        organization_name: str,
        company_id: str | None = None,
    ) -> tuple[OrganizationRecord, MembershipRecord]:
        effective_company_id = company_id.strip() if company_id else _to_company_slug(organization_name)

        existing = self.organization_repository.get_organization_by_company_id(
            effective_company_id
        )
        if existing is not None:
            raise ValueError("El company_id ya existe")

        organization = self.organization_repository.create_organization(
            name=organization_name.strip(),
            company_id=effective_company_id,
        )
        membership = self.membership_repository.add_membership(
            user_id=user_id,
            org_id=organization.org_id,
            role="owner",
        )
        return organization, membership

    def resolve_company_id(
        self,
        principal: AuthPrincipal,
        requested_company_id: str | None,
    ) -> str:
        memberships = self.membership_repository.list_memberships(principal.user_id)
        allowed_org_ids = {membership.org_id for membership in memberships}

        if requested_company_id:
            organization = self.organization_repository.get_organization_by_company_id(
                requested_company_id
            )
            if organization is None or organization.org_id not in allowed_org_ids:
                raise TenantForbiddenError("No tenes acceso a ese tenant")
            return organization.company_id

        if principal.active_org_id:
            if principal.active_org_id not in allowed_org_ids:
                raise TenantForbiddenError("Org activa no autorizada")
            organization = self.organization_repository.get_organization(principal.active_org_id)
            if organization is None:
                raise TenantContextError("No se encontro la org activa")
            return organization.company_id

        if len(memberships) == 1:
            only_org = self.organization_repository.get_organization(memberships[0].org_id)
            if only_org is None:
                raise TenantContextError("No se encontro la org del usuario")
            return only_org.company_id

        if not memberships:
            raise TenantForbiddenError("Usuario sin membresias")

        raise TenantContextError(
            "Usuario con multiples organizaciones: especifica company_id"
        )
