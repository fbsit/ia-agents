from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from clasificacion_langchain.agents.service import AgentDocumentNotFoundError, AgentValidationError
from clasificacion_langchain.api.schemas import (
    AgentCreatePayload,
    AgentChatRequestPayload,
    AgentChatResponsePayload,
    AgentDocumentPayload,
    AgentFeedbackSummaryPayload,
    AgentIndexPayload,
    AgentIndexStatusPayload,
    AgentPayload,
    AgentSetupStatusPayload,
    AgentWhatsAppConfigPayload,
    AgentWhatsAppConfigUpdatePayload,
    AgentWhatsAppValidationPayload,
    AgentWidgetConfigPayload,
    InternalAgentDocumentUploadPayload,
    MediaTranscriptionRequestPayload,
    MediaTranscriptionPayload,
    AgentUpdatePayload,
    TenantLlmSettingsPayload,
    TenantLlmSettingsUpdatePayload,
)
from clasificacion_langchain.api.support.agent_views import (
    index_status_payload,
    rebuild_index_payload,
    setup_status_payload,
    whatsapp_validation_payload,
    whatsapp_webhook_url,
    widget_config_payload,
)
from clasificacion_langchain.api.support.auth import require_internal_context
from clasificacion_langchain.api.support.presenters import (
    document_payload,
    settings_payload,
    to_agent_feedback_summary_payload,
    to_agent_payload,
    whatsapp_config_payload,
)
from clasificacion_langchain.api.support.media import transcribe_audio_bytes
from clasificacion_langchain.api.support.widget import public_widget_api_base_url_internal

from ..dependencies import get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(prefix="/internal/ai", tags=["internal"])


def _resolve_internal_agent(runtime: RuntimeContainer, company_id: str, org_id: str, agent_id: str):
    agent = runtime.agent_service.repository.get_agent(agent_id)
    if agent is None or agent.company_id != company_id or agent.org_id != org_id:
        raise HTTPException(status_code=404, detail="Agente no encontrado para el tenant")
    return agent


def internal_context(
    x_company_id: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_platform_signature: str | None = Header(default=None),
    x_platform_timestamp: str | None = Header(default=None),
) -> tuple[str, str, str, str]:
    """Dependency: valida headers de gateway y devuelve (company_id, org_id, user_id, request_id)."""
    return require_internal_context(
        x_company_id, x_org_id, x_user_id, x_request_id, x_platform_signature, x_platform_timestamp
    )


def internal_agent(
    agent_id: str,
    request: Request,
    context: tuple[str, str, str, str] = Depends(internal_context),
):
    """Dependency: agente resuelto y validado contra el tenant del gateway."""
    company_id, org_id, _, _ = context
    return _resolve_internal_agent(get_runtime(request), company_id, org_id, agent_id)


@router.post("/agents", response_model=AgentPayload)
def internal_create_agent(
    payload: AgentCreatePayload,
    request: Request,
    x_company_id: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_platform_signature: str | None = Header(default=None),
    x_platform_timestamp: str | None = Header(default=None),
) -> AgentPayload:
    runtime = get_runtime(request)
    company_id, org_id, _, _ = require_internal_context(
        x_company_id, x_org_id, x_user_id, x_request_id, x_platform_signature, x_platform_timestamp
    )
    organization = runtime.tenancy_service.organization_repository.get_organization(org_id)
    if organization is None or organization.company_id != company_id:
        raise HTTPException(status_code=400, detail="No se encontro la organizacion del tenant")

    agent = runtime.agent_service.create_agent(
        org_id=org_id,
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
    )
    return to_agent_payload(agent, 0)


@router.get("/agents", response_model=list[AgentPayload])
def internal_list_agents(
    request: Request,
    x_company_id: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_platform_signature: str | None = Header(default=None),
    x_platform_timestamp: str | None = Header(default=None),
) -> list[AgentPayload]:
    runtime = get_runtime(request)
    company_id, org_id, _, _ = require_internal_context(
        x_company_id, x_org_id, x_user_id, x_request_id, x_platform_signature, x_platform_timestamp
    )
    rows = runtime.agent_service.list_agents_with_document_counts({org_id}, company_id=company_id)
    return [to_agent_payload(agent, count) for agent, count in rows]


@router.patch("/agents/{agent_id}", response_model=AgentPayload)
def internal_update_agent(
    agent_id: str,
    payload: AgentUpdatePayload,
    request: Request,
    x_company_id: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_platform_signature: str | None = Header(default=None),
    x_platform_timestamp: str | None = Header(default=None),
) -> AgentPayload:
    runtime = get_runtime(request)
    company_id, org_id, _, _ = require_internal_context(
        x_company_id, x_org_id, x_user_id, x_request_id, x_platform_signature, x_platform_timestamp
    )
    agent = _resolve_internal_agent(runtime, company_id, org_id, agent_id)
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
    )
    return to_agent_payload(updated, len(runtime.agent_service.list_documents(updated.agent_id)))


@router.delete("/agents/{agent_id}", response_model=dict[str, str])
def internal_delete_agent(
    agent_id: str,
    request: Request,
    x_company_id: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_platform_signature: str | None = Header(default=None),
    x_platform_timestamp: str | None = Header(default=None),
) -> dict[str, str]:
    runtime = get_runtime(request)
    company_id, org_id, _, _ = require_internal_context(
        x_company_id, x_org_id, x_user_id, x_request_id, x_platform_signature, x_platform_timestamp
    )
    agent = _resolve_internal_agent(runtime, company_id, org_id, agent_id)
    removed = runtime.agent_service.delete_agent(agent)
    return {"status": "ok", "agent_id": removed.agent_id}


@router.get("/settings/llm", response_model=TenantLlmSettingsPayload)
def internal_get_llm_settings(
    request: Request,
    x_company_id: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_platform_signature: str | None = Header(default=None),
    x_platform_timestamp: str | None = Header(default=None),
) -> TenantLlmSettingsPayload:
    runtime = get_runtime(request)
    company_id, _, _, _ = require_internal_context(
        x_company_id, x_org_id, x_user_id, x_request_id, x_platform_signature, x_platform_timestamp
    )
    return settings_payload(runtime.llm_settings_service.get(company_id))


@router.put("/settings/llm", response_model=TenantLlmSettingsPayload)
def internal_update_llm_settings(
    payload: TenantLlmSettingsUpdatePayload,
    request: Request,
    x_company_id: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_platform_signature: str | None = Header(default=None),
    x_platform_timestamp: str | None = Header(default=None),
) -> TenantLlmSettingsPayload:
    runtime = get_runtime(request)
    company_id, _, _, _ = require_internal_context(
        x_company_id, x_org_id, x_user_id, x_request_id, x_platform_signature, x_platform_timestamp
    )
    settings = runtime.llm_settings_service.update(
        company_id=company_id,
        generation_provider=payload.generation_provider,
        openai_model=payload.openai_model,
        anthropic_model=payload.anthropic_model,
        openai_api_key=payload.openai_api_key,
        anthropic_api_key=payload.anthropic_api_key,
        clear_openai_api_key=payload.clear_openai_api_key,
        clear_anthropic_api_key=payload.clear_anthropic_api_key,
    )
    return settings_payload(settings)


@router.post("/agents/{agent_id}/chat", response_model=AgentChatResponsePayload)
def internal_agent_chat(
    agent_id: str,
    payload: AgentChatRequestPayload,
    request: Request,
    x_company_id: str | None = Header(default=None),
    x_org_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    x_platform_signature: str | None = Header(default=None),
    x_platform_timestamp: str | None = Header(default=None),
) -> AgentChatResponsePayload:
    runtime = get_runtime(request)
    company_id, _, user_id, _ = require_internal_context(
        x_company_id, x_org_id, x_user_id, x_request_id, x_platform_signature, x_platform_timestamp
    )
    agent = runtime.agent_service.repository.get_agent(agent_id)
    if agent is None or agent.company_id != company_id:
        raise HTTPException(status_code=404, detail="Agente no encontrado para el tenant")
    session_id = (payload.session_id or user_id).strip()
    answer = runtime.agent_service.chat(
        agent=agent,
        message=payload.message,
        company_id=company_id,
        top_k=payload.top_k,
        session_id=session_id,
        external_user_id=user_id,
        channel=payload.channel or "internal",
        use_openai=payload.use_openai_generation,
        generation_provider=payload.generation_provider,
        generation_model=payload.generation_model,
    )
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


# --- Documentos -----------------------------------------------------------


@router.get("/agents/{agent_id}/documents", response_model=list[AgentDocumentPayload])
def internal_list_documents(
    request: Request,
    agent=Depends(internal_agent),
) -> list[AgentDocumentPayload]:
    runtime = get_runtime(request)
    return [document_payload(item) for item in runtime.agent_service.list_documents(agent.agent_id)]


@router.post("/agents/{agent_id}/documents", response_model=AgentDocumentPayload)
def internal_upload_document(
    payload: InternalAgentDocumentUploadPayload,
    request: Request,
    agent=Depends(internal_agent),
) -> AgentDocumentPayload:
    runtime = get_runtime(request)
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="content_base64 invalido") from exc
    try:
        document = runtime.agent_service.save_document(
            agent=agent,
            filename=payload.filename,
            content=content,
            operational_section=payload.operational_section,
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return document_payload(document)


@router.delete("/agents/{agent_id}/documents/{document_id}", response_model=dict[str, str])
def internal_delete_document(
    document_id: str,
    request: Request,
    agent=Depends(internal_agent),
) -> dict[str, str]:
    runtime = get_runtime(request)
    try:
        document = runtime.agent_service.delete_document(agent, document_id)
    except AgentDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "document_id": document.document_id}


# --- Indice y setup -------------------------------------------------------


@router.post("/agents/{agent_id}/index/rebuild", response_model=AgentIndexPayload)
def internal_rebuild_index(request: Request, agent=Depends(internal_agent)) -> AgentIndexPayload:
    return rebuild_index_payload(get_runtime(request), agent)


@router.get("/agents/{agent_id}/index/status", response_model=AgentIndexStatusPayload)
def internal_index_status(request: Request, agent=Depends(internal_agent)) -> AgentIndexStatusPayload:
    return index_status_payload(get_runtime(request), agent)


@router.get("/agents/{agent_id}/setup-status", response_model=AgentSetupStatusPayload)
def internal_setup_status(request: Request, agent=Depends(internal_agent)) -> AgentSetupStatusPayload:
    return setup_status_payload(get_runtime(request), agent)


# --- Widget y canales -----------------------------------------------------


@router.get("/agents/{agent_id}/widget-config", response_model=AgentWidgetConfigPayload)
def internal_widget_config(
    agent=Depends(internal_agent),
    x_public_base_url: str | None = Header(default=None),
) -> AgentWidgetConfigPayload:
    return widget_config_payload(agent, public_widget_api_base_url_internal(x_public_base_url))


@router.get("/agents/{agent_id}/channels/whatsapp/config", response_model=AgentWhatsAppConfigPayload)
def internal_get_whatsapp_config(
    request: Request,
    agent=Depends(internal_agent),
    x_public_base_url: str | None = Header(default=None),
) -> AgentWhatsAppConfigPayload:
    runtime = get_runtime(request)
    base_url = public_widget_api_base_url_internal(x_public_base_url)
    return whatsapp_config_payload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        webhook_url=whatsapp_webhook_url(base_url, agent.agent_id),
        config=runtime.agent_service.get_whatsapp_channel_config(agent),
    )


@router.put("/agents/{agent_id}/channels/whatsapp/config", response_model=AgentWhatsAppConfigPayload)
def internal_update_whatsapp_config(
    payload: AgentWhatsAppConfigUpdatePayload,
    request: Request,
    agent=Depends(internal_agent),
    x_public_base_url: str | None = Header(default=None),
) -> AgentWhatsAppConfigPayload:
    runtime = get_runtime(request)
    base_url = public_widget_api_base_url_internal(x_public_base_url)
    config = runtime.agent_service.update_whatsapp_channel_config(
        agent,
        phone_number_id=payload.phone_number_id,
        business_account_id=payload.business_account_id,
        verify_token=payload.verify_token,
    )
    return whatsapp_config_payload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        webhook_url=whatsapp_webhook_url(base_url, agent.agent_id),
        config=config,
    )


@router.post("/agents/{agent_id}/channels/whatsapp/validate", response_model=AgentWhatsAppValidationPayload)
def internal_validate_whatsapp_config(
    request: Request,
    agent=Depends(internal_agent),
    x_public_base_url: str | None = Header(default=None),
) -> AgentWhatsAppValidationPayload:
    runtime = get_runtime(request)
    base_url = public_widget_api_base_url_internal(x_public_base_url)
    config = runtime.agent_service.get_whatsapp_channel_config(agent)
    return whatsapp_validation_payload(agent, config, whatsapp_webhook_url(base_url, agent.agent_id))


# --- Feedback -------------------------------------------------------------


@router.get("/agents/{agent_id}/feedback/summary", response_model=AgentFeedbackSummaryPayload)
def internal_feedback_summary(
    request: Request,
    agent=Depends(internal_agent),
    days: int = Query(default=30, ge=1, le=365),
) -> AgentFeedbackSummaryPayload:
    runtime = get_runtime(request)
    summary = runtime.feedback_service.summary(agent.company_id, agent.agent_id, since_days=days)
    return to_agent_feedback_summary_payload(summary)


# --- Media ----------------------------------------------------------------


@router.post("/media/transcriptions", response_model=MediaTranscriptionPayload)
def internal_media_transcriptions(payload: MediaTranscriptionRequestPayload) -> MediaTranscriptionPayload:
    try:
        audio_bytes = base64.b64decode(payload.content_base64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="content_base64 invalido") from exc
    return transcribe_audio_bytes(
        audio_bytes=audio_bytes,
        filename=payload.filename,
        mime_type=payload.mime_type,
        language_hint=payload.language_hint,
    )
