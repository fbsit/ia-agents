from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from clasificacion_langchain.agents.service import (
    AgentForbiddenError,
    AgentNotFoundError,
    AgentValidationError,
)
from clasificacion_langchain.api.schemas import (
    AgentChatRequestPayload,
    AgentChatResponsePayload,
    AgentCreatePayload,
    AgentPayload,
    AgentUpdatePayload,
    AgentWebAnalysisPayload,
    AgentWebAnalysisRequestPayload,
)
from clasificacion_langchain.api.support.presenters import to_agent_payload
from clasificacion_langchain.shared.ml.agent_tools import AgentToolset

from ..dependencies import (
    get_accessible_agent,
    get_allowed_org_ids,
    get_principal,
    get_runtime,
    resolve_company_id,
)
from ..runtime import RuntimeContainer


router = APIRouter(prefix="/agents", tags=["agents"])
@router.post("", response_model=AgentPayload)
def create_agent(
    payload: AgentCreatePayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentPayload:
    company_id = resolve_company_id(runtime, principal, payload.company_id)
    organization = runtime.tenancy_service.organization_repository.get_organization_by_company_id(
        company_id
    )
    if organization is None:
        raise HTTPException(status_code=400, detail="No se encontro la organizacion del tenant")

    try:
        agent = runtime.agent_service.create_agent(
            org_id=organization.org_id,
            company_id=company_id,
            name=payload.name,
            objective=payload.objective,
            tone=payload.tone,
            description=payload.description,
            rag_backend=payload.rag_backend,
            generation_provider=payload.generation_provider,
            use_openai_generation=payload.use_openai_generation,
            openai_model=payload.openai_model or "gpt-4o-mini",
            clubhx_tenant_id=payload.clubhx_tenant_id,
            clubhx_shop_domain=payload.clubhx_shop_domain,
            clubhx_storefront_url=payload.clubhx_storefront_url,
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    documents = runtime.agent_service.list_documents(agent.agent_id)
    return to_agent_payload(agent, len(documents))


@router.get("", response_model=list[AgentPayload])
def list_agents(
    company_id: str | None = None,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> list[AgentPayload]:
    allowed_org_ids = get_allowed_org_ids(runtime, principal)
    rows = runtime.agent_service.list_agents_with_document_counts(allowed_org_ids, company_id=company_id)
    return [to_agent_payload(agent, count) for agent, count in rows]


@router.patch("/{agent_id}", response_model=AgentPayload)
def update_agent(
    agent_id: str,
    payload: AgentUpdatePayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    try:
        updated = runtime.agent_service.update_agent(
            agent,
            name=payload.name,
            objective=payload.objective,
            tone=payload.tone,
            description=payload.description,
            rag_backend=payload.rag_backend,
            generation_provider=payload.generation_provider,
            use_openai_generation=payload.use_openai_generation,
            openai_model=payload.openai_model,
            clubhx_tenant_id=payload.clubhx_tenant_id,
            clubhx_shop_domain=payload.clubhx_shop_domain,
            clubhx_storefront_url=payload.clubhx_storefront_url,
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_agent_payload(updated, len(runtime.agent_service.list_documents(updated.agent_id)))


@router.delete("/{agent_id}", response_model=dict[str, str])
def delete_agent(
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> dict[str, str]:
    agent = get_accessible_agent(runtime, principal, agent_id)
    removed = runtime.agent_service.delete_agent(agent)
    return {"status": "ok", "agent_id": removed.agent_id}


@router.post("/{agent_id}/tools/analyze-url", response_model=AgentWebAnalysisPayload)
def analyze_web_url(
    agent_id: str,
    payload: AgentWebAnalysisRequestPayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentWebAnalysisPayload:
    get_accessible_agent(runtime, principal, agent_id)
    try:
        result = AgentToolset.analyze_web_url(
            payload.url,
            timeout_seconds=payload.timeout_seconds,
            max_chars=payload.max_chars,
            max_points=payload.max_points,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AgentWebAnalysisPayload(**result)


@router.post("/{agent_id}/chat", response_model=AgentChatResponsePayload)
def chat_with_agent(
    agent_id: str,
    payload: AgentChatRequestPayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentChatResponsePayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    company_id = resolve_company_id(runtime, principal, agent.company_id)
    session_id = (payload.session_id or principal.user_id).strip()
    try:
        answer = runtime.agent_service.chat(
            agent=agent,
            message=payload.message,
            company_id=company_id,
            top_k=payload.top_k,
            session_id=session_id,
            channel=payload.channel or "api",
            use_openai=payload.use_openai_generation,
            generation_provider=payload.generation_provider,
            generation_model=payload.generation_model,
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AgentChatResponsePayload(
        agent_id=agent.agent_id,
        company_id=company_id,
        session_id=session_id,
        answer=answer.answer,
        sources=answer.sources,
        intent_label=answer.intent_label,
        route=answer.route,
        route_reason=answer.route_reason,
        response_mode=answer.response_mode,
        fallback_applied=answer.fallback_applied,
        retrieval_min_score=answer.retrieval_min_score,
        redirect_to=answer.redirect_to,
        workflow_action=answer.workflow_action,
        cart_action=answer.cart_action,
        cart_actions=answer.cart_actions,
        products=answer.products,
    )
