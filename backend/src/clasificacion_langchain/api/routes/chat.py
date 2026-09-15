from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from clasificacion_langchain.api.schemas import ChatRequestPayload, ChatResponsePayload
from clasificacion_langchain.api.support.auth import require_principal
from clasificacion_langchain.auth.schemas import AuthPrincipal
from clasificacion_langchain.chat.schemas import ChatRequest
from clasificacion_langchain.runtime.builders import chat_auth_compat_mode

from ..dependencies import get_runtime, resolve_company_id
from ..runtime import RuntimeContainer


router = APIRouter(tags=["chat"])


def _optional_principal(
    authorization: str | None = Header(default=None),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AuthPrincipal | None:
    """
    Modo de migracion de `/chat` (CHAT_AUTH_COMPAT_MODE):
    - con bearer token: siempre se valida y se resuelve tenant contra membresias;
    - sin token y compat=true: se acepta el payload legacy (company_id + session_id);
    - sin token y compat=false: 401.
    """
    if authorization:
        return require_principal(authorization, runtime.token_service)
    if not chat_auth_compat_mode():
        raise HTTPException(status_code=401, detail="Este endpoint requiere autenticacion")
    return None


@router.post("/chat", response_model=ChatResponsePayload)
def chat(
    payload: ChatRequestPayload,
    principal: AuthPrincipal | None = Depends(_optional_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> ChatResponsePayload:
    company_id = payload.company_id
    session_id = payload.session_id
    if principal is not None:
        company_id = resolve_company_id(runtime, principal, payload.company_id)
        session_id = session_id or principal.user_id

    if not company_id:
        raise HTTPException(status_code=400, detail="company_id es requerido")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id es requerido")

    try:
        result = runtime.chat_service.chat(
            ChatRequest(
                company_id=company_id,
                session_id=session_id.strip(),
                message=payload.message,
                top_k=payload.top_k,
                generation_provider=payload.generation_provider,
                generation_model=payload.generation_model,
                use_openai_generation=payload.use_openai_generation,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ChatResponsePayload(
        trace_id=result.trace_id,
        company_id=result.company_id,
        session_id=result.session_id,
        answer=result.answer,
        route=result.route,
        route_reason=result.route_reason,
        intent_label=result.intent_label,
        intent_confidence=result.intent_confidence,
        sources=result.sources,
        escalation_required=result.escalation_required,
    )
