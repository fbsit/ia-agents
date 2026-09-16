from __future__ import annotations

import logging
import os

from clasificacion_langchain.channels.meta_whatsapp_api import MetaWhatsAppClient

logger = logging.getLogger(__name__)


def send_whatsapp_reply(*, phone_number_id: str, to_number: str, text: str) -> bool:
    """
    Envia un mensaje de texto real a WhatsApp via la Graph API de Meta.
    Extraido de api/routes/whatsapp_webhooks.py para que tanto la respuesta
    automatica del bot como una respuesta humana (conversations/reply) usen
    el mismo camino real de entrega, en vez de duplicar la construccion del
    cliente en cada lugar.

    Usa el token global WHATSAPP_ACCESS_TOKEN (un solo token para todos los
    tenants hoy; no hay token por agente todavia). No levanta excepcion: el
    llamador solo necesita saber si se pudo entregar o no.
    """
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    if not access_token:
        logger.warning("whatsapp_send_skipped reason=missing_access_token phone_number_id=%s", phone_number_id)
        return False
    client = MetaWhatsAppClient(access_token=access_token)
    try:
        client.send_text_message(phone_number_id=phone_number_id, to_number=to_number, text=text)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("whatsapp_send_failed phone_number_id=%s to=%s detail=%s", phone_number_id, to_number, exc)
        return False
