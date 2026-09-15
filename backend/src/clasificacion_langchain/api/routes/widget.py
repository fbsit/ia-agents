from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from clasificacion_langchain.api.schemas import (
    AgentWidgetConfigPayload,
    PublicWidgetChatRequestPayload,
    PublicWidgetChatResponsePayload,
)
from clasificacion_langchain.api.support.agent_views import widget_config_payload
from clasificacion_langchain.api.support.widget import (
    public_widget_api_base_url,
    public_widget_client_id,
    public_widget_origin_allowed,
    public_widget_rate_limit_retry_after,
    public_widget_session_id,
    public_widget_token,
)

from ..dependencies import get_accessible_agent, get_principal, get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(tags=["widget"])


@router.get("/agents/{agent_id}/widget-config", response_model=AgentWidgetConfigPayload)
def get_widget_config(
    request: Request,
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentWidgetConfigPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    return widget_config_payload(agent, public_widget_api_base_url(request))


@router.post("/public/widget/chat", response_model=PublicWidgetChatResponsePayload)
def public_widget_chat(
    payload: PublicWidgetChatRequestPayload,
    request: Request,
    origin: str | None = Header(default=None),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> PublicWidgetChatResponsePayload:
    if not public_widget_origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin no permitido")
    agent = runtime.agent_service.repository.get_agent(payload.widget_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Widget no encontrado")
    expected_token = public_widget_token(agent.agent_id, agent.company_id)
    if not hmac.compare_digest(expected_token, payload.widget_token):
        # 403 (no 401): el widget no autentica usuarios, valida un token de embed.
        raise HTTPException(status_code=403, detail="widget_token invalido")
    client_id = public_widget_client_id(request)
    retry_after = public_widget_rate_limit_retry_after(payload.widget_id, client_id)
    if retry_after is not None:
        raise HTTPException(status_code=429, detail=f"Rate limit excedido. Retry after {retry_after}s")
    session_id = public_widget_session_id(payload.widget_id, payload.session_id)
    answer = runtime.agent_service.chat(
        agent=agent,
        message=payload.message,
        company_id=agent.company_id,
        top_k=payload.top_k,
        session_id=session_id,
        visitor_id=payload.visitor_id,
        external_user_id=payload.external_user_id,
        channel="widget",
    )
    return PublicWidgetChatResponsePayload(
        widget_id=payload.widget_id,
        session_id=session_id,
        answer=answer.answer,
        sources=answer.sources,
        route=answer.route,
        intent_label=answer.intent_label,
        response_mode=answer.response_mode,
        redirect_to=answer.redirect_to,
        workflow_action=answer.workflow_action,
        cart_action=answer.cart_action,
        cart_actions=answer.cart_actions,
        products=answer.products,
    )
