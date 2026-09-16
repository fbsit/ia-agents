from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from clasificacion_langchain.channels.idempotency import InMemoryIdempotencyStore
from clasificacion_langchain.channels.whatsapp import parse_whatsapp_messages
from clasificacion_langchain.channels.whatsapp_send import send_whatsapp_reply

from ..dependencies import get_runtime


logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp-webhooks"])
_wa_idempotency = InMemoryIdempotencyStore(ttl_seconds=300)


def _find_agent_by_phone_number_id(runtime, phone_number_id: str):
    for agent in runtime.agent_service.repository.list_all_agents():
        config = runtime.agent_service.get_whatsapp_channel_config(agent)
        if str(config.get("phone_number_id") or "").strip() == phone_number_id:
            return agent
    return None


@router.get("/internal/ai/agents/{agent_id}/channels/whatsapp/webhook", response_class=PlainTextResponse)
def verify_whatsapp_webhook(
    agent_id: str,
    request: Request,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> str:
    runtime = get_runtime(request)
    agent = runtime.agent_service.repository.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    config = runtime.agent_service.get_whatsapp_channel_config(agent)
    expected = str(config.get("verify_token") or "").strip()
    if hub_mode != "subscribe" or not expected or hub_verify_token != expected:
        raise HTTPException(status_code=403, detail="Verificacion de webhook invalida")
    return str(hub_challenge or "")


@router.post("/internal/ai/agents/{agent_id}/channels/whatsapp/webhook")
async def receive_whatsapp_webhook(agent_id: str, request: Request) -> dict[str, object]:
    runtime = get_runtime(request)
    agent = runtime.agent_service.repository.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    payload = await request.json()
    messages = parse_whatsapp_messages(payload)
    processed = 0
    sent = 0
    for incoming in messages:
        if incoming.phone_number_id and incoming.phone_number_id != (runtime.agent_service.get_whatsapp_channel_config(agent).get("phone_number_id") or ""):
            continue
        if incoming.message_id and not _wa_idempotency.mark_if_new(incoming.message_id):
            continue
        processed += 1
        if incoming.message_type != "text" or not incoming.text.strip():
            continue

        # Si una persona ya tomo esta conversacion (ver /conversations/{id}/takeover),
        # el bot no responde: solo se registra el mensaje entrante para que la
        # persona lo vea en la consola.
        status = runtime.chat_audit_service.get_conversation_status(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            session_id=incoming.session_id,
            channel="whatsapp",
        )
        if status == "human_active":
            runtime.chat_audit_service.add_customer_message(
                company_id=agent.company_id,
                agent_id=agent.agent_id,
                session_id=incoming.session_id,
                channel="whatsapp",
                message_text=incoming.text,
                external_user_id=incoming.from_number,
            )
            continue

        answer = runtime.agent_service.chat(
            agent=agent,
            message=incoming.text,
            company_id=agent.company_id,
            session_id=incoming.session_id,
            external_user_id=incoming.from_number,
            channel="whatsapp",
        )
        if send_whatsapp_reply(phone_number_id=incoming.phone_number_id, to_number=incoming.from_number, text=answer.answer):
            sent += 1
    return {"status": "ok", "processed": processed, "sent": sent}
