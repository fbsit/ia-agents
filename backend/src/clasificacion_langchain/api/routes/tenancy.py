from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from ..dependencies import get_principal, get_runtime
from ..runtime import RuntimeContainer


class CreateOrganizationPayload(BaseModel):
    """Acepta `name` (contrato Python) y `organization_name` (contrato platform-api)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=2, validation_alias=AliasChoices("name", "organization_name"))
    company_id: str | None = Field(default=None, min_length=1)


router = APIRouter(tags=["tenancy"])


@router.post("/orgs")
def create_org(
    payload: CreateOrganizationPayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> dict[str, object]:
    try:
        organization, membership = runtime.tenancy_service.onboard_organization(
            user_id=principal.user_id,
            organization_name=payload.name,
            company_id=payload.company_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "org_id": organization.org_id,
        "name": organization.name,
        "company_id": organization.company_id,
        "membership": {"user_id": membership.user_id, "role": membership.role},
    }


@router.get("/orgs")
def list_orgs(
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> list[dict[str, object]]:
    memberships = runtime.tenancy_service.membership_repository.list_memberships(principal.user_id)
    rows: list[dict[str, object]] = []
    for membership in memberships:
        organization = runtime.tenancy_service.organization_repository.get_organization(
            membership.org_id
        )
        if organization is None:
            continue
        rows.append(
            {
                "org_id": organization.org_id,
                "name": organization.name,
                "company_id": organization.company_id,
                "role": membership.role,
            }
        )
    return rows
