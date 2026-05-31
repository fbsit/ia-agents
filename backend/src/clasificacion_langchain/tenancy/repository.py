from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class OrganizationRecord:
    org_id: str
    name: str
    company_id: str
    created_at: datetime


@dataclass
class MembershipRecord:
    user_id: str
    org_id: str
    role: str
    created_at: datetime


class OrganizationRepository(Protocol):
    def create_organization(self, name: str, company_id: str) -> OrganizationRecord:
        ...

    def get_organization(self, org_id: str) -> OrganizationRecord | None:
        ...

    def get_organization_by_company_id(self, company_id: str) -> OrganizationRecord | None:
        ...


class MembershipRepository(Protocol):
    def add_membership(self, user_id: str, org_id: str, role: str) -> MembershipRecord:
        ...

    def list_memberships(self, user_id: str) -> list[MembershipRecord]:
        ...
