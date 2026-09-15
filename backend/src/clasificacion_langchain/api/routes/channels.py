from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from clasificacion_langchain.api.schemas import (
    AgentWhatsAppConfigPayload,
    AgentWhatsAppConfigUpdatePayload,
    AgentWhatsAppValidationPayload,
)
from clasificacion_langchain.api.support.agent_views import whatsapp_validation_payload, whatsapp_webhook_url
from clasificacion_langchain.api.support.presenters import whatsapp_config_payload

from ..dependencies import get_accessible_agent, get_principal, get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(tags=["channels"])


def _webhook_url(request: Request, agent_id: str) -> str:
    return whatsapp_webhook_url(str(request.base_url), agent_id)


@router.get("/agents/{agent_id}/channels/whatsapp/config", response_model=AgentWhatsAppConfigPayload)
def get_whatsapp_config(
    request: Request,
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentWhatsAppConfigPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    config = runtime.agent_service.get_whatsapp_channel_config(agent)
    return whatsapp_config_payload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        webhook_url=_webhook_url(request, agent.agent_id),
        config=config,
    )


@router.put("/agents/{agent_id}/channels/whatsapp/config", response_model=AgentWhatsAppConfigPayload)
def update_whatsapp_config(
    request: Request,
    agent_id: str,
    payload: AgentWhatsAppConfigUpdatePayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentWhatsAppConfigPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    config = runtime.agent_service.update_whatsapp_channel_config(
        agent,
        phone_number_id=payload.phone_number_id,
        business_account_id=payload.business_account_id,
        verify_token=payload.verify_token,
    )
    return whatsapp_config_payload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        webhook_url=_webhook_url(request, agent.agent_id),
        config=config,
    )


@router.post("/agents/{agent_id}/channels/whatsapp/validate", response_model=AgentWhatsAppValidationPayload)
def validate_whatsapp_config(
    request: Request,
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentWhatsAppValidationPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    config = runtime.agent_service.get_whatsapp_channel_config(agent)
    return whatsapp_validation_payload(agent, config, _webhook_url(request, agent.agent_id))
