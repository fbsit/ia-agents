from __future__ import annotations

from fastapi import Header, HTTPException, Request

from clasificacion_langchain.agents.service import (
    AgentForbiddenError,
    AgentNotFoundError,
)
from clasificacion_langchain.auth.schemas import AuthPrincipal
from clasificacion_langchain.api.support.auth import require_principal
from clasificacion_langchain.tenancy.service import TenantContextError, TenantForbiddenError

from .runtime import RuntimeContainer


def get_runtime(request: Request) -> RuntimeContainer:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Runtime no inicializado")
    return runtime


def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthPrincipal:
    runtime = get_runtime(request)
    return require_principal(authorization, runtime.token_service)


def get_allowed_org_ids(runtime: RuntimeContainer, principal: AuthPrincipal) -> set[str]:
    memberships = runtime.auth_service.membership_repository.list_memberships(principal.user_id)
    return {membership.org_id for membership in memberships}


def resolve_company_id(
    runtime: RuntimeContainer,
    principal: AuthPrincipal,
    requested_company_id: str | None,
) -> str:
    try:
        return runtime.tenancy_service.resolve_company_id(principal, requested_company_id)
    except TenantContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TenantForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def get_accessible_agent(runtime: RuntimeContainer, principal: AuthPrincipal, agent_id: str):
    allowed_org_ids = get_allowed_org_ids(runtime, principal)
    try:
        return runtime.agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def resolve_report_companies(
    runtime: RuntimeContainer,
    principal: AuthPrincipal,
    company_id: str | None,
) -> list[str]:
    if company_id:
        return [resolve_company_id(runtime, principal, company_id)]

    memberships = runtime.tenancy_service.membership_repository.list_memberships(principal.user_id)
    discovered: set[str] = set()
    for membership in memberships:
        organization = runtime.tenancy_service.organization_repository.get_organization(
            membership.org_id
        )
        if organization is not None:
            discovered.add(organization.company_id)
    return sorted(discovered)
