from __future__ import annotations

"""
Vistas de agente compartidas entre rutas autenticadas y rutas internas (gateway).

Cada helper recibe el agente ya resuelto/autorizado y devuelve el payload final,
de modo que ambos routers exponen exactamente el mismo contrato.
"""

import os

from fastapi import HTTPException

from clasificacion_langchain.agents.service import AgentValidationError
from clasificacion_langchain.api.schemas import (
    AgentIndexPayload,
    AgentIndexStatusPayload,
    AgentSetupStatusPayload,
    AgentSetupStepPayload,
    AgentWhatsAppValidationPayload,
    AgentWidgetConfigPayload,
)
from clasificacion_langchain.api.support.widget import (
    is_agent_whatsapp_config_ready,
    public_widget_rate_limit_max_requests,
    public_widget_rate_limit_window_seconds,
    public_widget_snippet,
    public_widget_token,
)

from ..runtime import RuntimeContainer


def whatsapp_webhook_url(base_url: str, agent_id: str) -> str:
    return f"{base_url.rstrip('/')}/internal/ai/agents/{agent_id}/channels/whatsapp/webhook"


def rebuild_index_payload(runtime: RuntimeContainer, agent) -> AgentIndexPayload:
    try:
        result = runtime.agent_service.rebuild_index(agent)
    except (AgentValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Falla del proveedor externo (p. ej. cuota de OpenAI embeddings) con backend explicito.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AgentIndexPayload(
        agent_id=agent.agent_id,
        backend=result.backend,
        total_documents=result.total_documents,
        total_chunks=result.total_chunks,
        companies=result.companies,
        index_path=str(result.index_path),
    )


def index_status_payload(runtime: RuntimeContainer, agent) -> AgentIndexStatusPayload:
    documents = runtime.agent_service.list_documents(agent.agent_id)
    failed = [item for item in documents if item.status == "failed"]
    indexed = [item for item in documents if item.status == "indexed"]
    uploaded = [item for item in documents if item.status == "uploaded"]
    last_error = next((item.error_message for item in reversed(failed) if item.error_message), None)
    return AgentIndexStatusPayload(
        agent_id=agent.agent_id,
        has_index=runtime.agent_service.ensure_index_local(agent),
        indexed_at=agent.indexed_at.isoformat() if agent.indexed_at else None,
        documents_total=len(documents),
        documents_indexed=len(indexed),
        documents_failed=len(failed),
        documents_uploaded=len(uploaded),
        last_error=last_error,
    )


def setup_status_payload(runtime: RuntimeContainer, agent) -> AgentSetupStatusPayload:
    documents = runtime.agent_service.list_documents(agent.agent_id)
    indexed_documents = [item for item in documents if item.status == "indexed"]
    whatsapp_config = runtime.agent_service.get_whatsapp_channel_config(agent)
    steps = [
        AgentSetupStepPayload(
            id="agent",
            label="Agente base",
            description="El agente fue creado con identidad y configuracion inicial.",
            ready=True,
            href=f"/api/agents/{agent.agent_id}",
        ),
        AgentSetupStepPayload(
            id="documents",
            label="Conocimiento",
            description="Subi documentos operativos del agente.",
            ready=bool(documents),
            href=f"/api/agents/{agent.agent_id}/documents",
        ),
        AgentSetupStepPayload(
            id="index",
            label="Indexacion",
            description="Reconstrui el indice RAG del agente.",
            ready=agent.indexed_at is not None,
            href=f"/api/agents/{agent.agent_id}/index/status",
        ),
        AgentSetupStepPayload(
            id="channel_whatsapp",
            label="Canal WhatsApp",
            description="Configura phone number id y verify token para publicar.",
            ready=is_agent_whatsapp_config_ready(whatsapp_config),
            href=f"/api/agents/{agent.agent_id}/channels/whatsapp/config",
        ),
    ]
    ready_count = len([step for step in steps if step.ready])
    next_step = next((step for step in steps if not step.ready), None)
    return AgentSetupStatusPayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        agent_name=agent.name,
        rag_backend=agent.rag_backend,
        progress_percent=int((ready_count / max(len(steps), 1)) * 100),
        ready_to_publish=all(step.ready for step in steps),
        next_href=next_step.href if next_step else None,
        documents_total=len(documents),
        documents_indexed=len(indexed_documents),
        test_messages=0,
        steps=steps,
    )


def widget_config_payload(agent, base_url: str) -> AgentWidgetConfigPayload:
    widget_id = agent.agent_id
    token = public_widget_token(agent.agent_id, agent.company_id)
    return AgentWidgetConfigPayload(
        agent_id=agent.agent_id,
        widget_id=widget_id,
        endpoint_url=f"{base_url.rstrip('/')}/public/widget/chat",
        messages_stream_url=f"{base_url.rstrip('/')}/public/widget/chat/stream",
        widget_token=token,
        allowed_origins=["*"],
        rate_limit_window_seconds=public_widget_rate_limit_window_seconds(),
        rate_limit_max_requests=public_widget_rate_limit_max_requests(),
        snippet_html=public_widget_snippet(base_url.rstrip("/"), widget_id, token),
    )


def whatsapp_validation_payload(agent, config: dict[str, str | None], webhook_url: str) -> AgentWhatsAppValidationPayload:
    ready = is_agent_whatsapp_config_ready(config)
    return AgentWhatsAppValidationPayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        ready=ready,
        has_phone_number_id=bool((config.get("phone_number_id") or "").strip()),
        has_verify_token=bool((config.get("verify_token") or "").strip()),
        server_has_access_token=bool(os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()),
        company_map_ready=True,
        webhook_url=webhook_url,
        messages=[] if ready else ["Faltan phone_number_id o verify_token"],
    )
