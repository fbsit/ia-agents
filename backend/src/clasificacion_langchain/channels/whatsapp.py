from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IncomingWhatsAppMessage:
    company_id: str
    session_id: str
    text: str
    phone_number_id: str
    from_number: str
    message_id: str


def parse_whatsapp_messages(
    payload: dict[str, object],
    company_map: dict[str, str] | None = None,
) -> list[IncomingWhatsAppMessage]:
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return []

    messages: list[IncomingWhatsAppMessage] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            continue

        for change in changes:
            if not isinstance(change, dict):
                continue

            value = change.get("value", {})
            if not isinstance(value, dict):
                continue

            metadata = value.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            phone_number_id = str(metadata.get("phone_number_id", "default_company"))
            company_id = company_map.get(phone_number_id, phone_number_id) if company_map else phone_number_id

            incoming = value.get("messages", [])
            if not isinstance(incoming, list):
                continue

            for item in incoming:
                if not isinstance(item, dict):
                    continue

                sender = str(item.get("from", ""))
                incoming_id = str(item.get("id", ""))
                message_type = str(item.get("type", ""))
                if message_type != "text":
                    continue

                text_block = item.get("text", {})
                if not isinstance(text_block, dict):
                    continue
                text = str(text_block.get("body", "")).strip()
                if not text or not sender:
                    continue

                messages.append(
                    IncomingWhatsAppMessage(
                        company_id=company_id,
                        session_id=sender,
                        text=text,
                        phone_number_id=phone_number_id,
                        from_number=sender,
                        message_id=incoming_id,
                    )
                )

    return messages
