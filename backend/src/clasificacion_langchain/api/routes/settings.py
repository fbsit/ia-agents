from __future__ import annotations

from fastapi import APIRouter, Depends

from clasificacion_langchain.api.schemas import (
    TenantLlmSettingsPayload,
    TenantLlmSettingsUpdatePayload,
)
from clasificacion_langchain.api.support.presenters import settings_payload

from ..dependencies import get_principal, get_runtime, resolve_company_id
from ..runtime import RuntimeContainer


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/llm", response_model=TenantLlmSettingsPayload)
def get_llm_settings(
    company_id: str | None = None,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> TenantLlmSettingsPayload:
    resolved_company_id = resolve_company_id(runtime, principal, company_id)
    return settings_payload(runtime.llm_settings_service.get(resolved_company_id))


@router.put("/llm", response_model=TenantLlmSettingsPayload)
def update_llm_settings(
    payload: TenantLlmSettingsUpdatePayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> TenantLlmSettingsPayload:
    resolved_company_id = resolve_company_id(runtime, principal, payload.company_id)
    settings = runtime.llm_settings_service.update(
        company_id=resolved_company_id,
        generation_provider=payload.generation_provider,
        openai_model=payload.openai_model,
        anthropic_model=payload.anthropic_model,
        openai_api_key=payload.openai_api_key,
        anthropic_api_key=payload.anthropic_api_key,
        clear_openai_api_key=payload.clear_openai_api_key,
        clear_anthropic_api_key=payload.clear_anthropic_api_key,
    )
    return settings_payload(settings)
