from __future__ import annotations

import asyncio
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

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
        # "widget_public" (no "widget" a secas) es el alias que reconoce todo
        # el modulo commerce (is_checkout_redirect_channel, format_public_widget_tool_payload,
        # etc.) para tratar la conversacion como canal web: con "widget" ninguna
        # de esas ramas web se activaba.
        channel="widget_public",
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


MESSAGES_STREAM_POLL_SECONDS = 2.0


@router.get("/public/widget/chat/stream")
async def public_widget_chat_stream(
    request: Request,
    widget_id: str = Query(...),
    widget_token: str = Query(...),
    session_id: str = Query(...),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> StreamingResponse:
    """
    SSE para que el widget reciba en vivo una respuesta humana (tomada desde
    Conversaciones en vivo): el widget solo reacciona a lo que el cliente
    pregunta, nunca al reves, asi que sin esto una respuesta humana quedaba
    guardada pero jamas llegaba al navegador si ya no habia otro mensaje del
    cliente disparando una nueva respuesta.
    """
    agent = runtime.agent_service.repository.get_agent(widget_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Widget no encontrado")
    expected_token = public_widget_token(agent.agent_id, agent.company_id)
    if not hmac.compare_digest(expected_token, widget_token):
        raise HTTPException(status_code=403, detail="widget_token invalido")

    async def event_generator():
        sent_human_messages = 0
        while True:
            if await request.is_disconnected():
                break
            # Sin channel: la misma conversacion web puede haber quedado con
            # "widget_public" (snippet propio) o "web" (integracion de ClubHx)
            # segun quien la origino; no vale la pena adivinar. list_messages
            # ya devuelve [] sin lanzar si la auditoria esta apagada.
            messages = runtime.chat_audit_service.list_messages(
                company_id=agent.company_id,
                agent_id=agent.agent_id,
                session_id=session_id,
                channel=None,
            )
            human_messages = [msg for msg in messages if msg.role == "human_agent"]
            for msg in human_messages[sent_human_messages:]:
                data = json.dumps({"role": msg.role, "text": msg.message_text, "created_at": msg.created_at.isoformat()})
                yield f"event: update\ndata: {data}\n\n"
            sent_human_messages = len(human_messages)
            await asyncio.sleep(MESSAGES_STREAM_POLL_SECONDS)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
