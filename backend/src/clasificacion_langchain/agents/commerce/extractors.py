from __future__ import annotations

import json
import logging
import re
from typing import Any

from clasificacion_langchain.agents.commerce.recent_products import (
    QUANTITY_WORDS,
    has_explicit_add_to_cart_intent,
    is_implicit_add_to_cart_message,
    is_quantity_only_followup,
    normalize_text,
    parse_quantity,
)


logger = logging.getLogger(__name__)


def has_explicit_cart_change_intent(message: str, mode: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    if is_implicit_add_to_cart_message(message) or is_quantity_only_followup(message):
        return True
    if mode == "remove":
        return bool(
            re.search(
                r"\b(?:quita|quitame|quitar|saca|sacame|sacar|remueve|remover|elimina|eliminar|borra|borrar|del|de|carrito)\b",
                normalized,
                flags=re.IGNORECASE,
            )
        )
    if mode == "set":
        return bool(
            re.search(
                r"\b(?:deja|dejame|dejar|solo|solamente|cambia|cambiar|actualiza|actualizar|modifica|modificar|necesito|pon|ponme|poner)\b",
                normalized,
                flags=re.IGNORECASE,
            )
        )
    return False


def is_affirmative_followup_message(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return normalized in {
        "adelante",
        "bueno",
        "confirmar",
        "confirmo",
        "continuemos",
        "correcto",
        "dale",
        "de una",
        "esta correcto",
        "listo",
        "ok",
        "oka",
        "procede",
        "proceder",
        "si",
        "si, confirmo",
        "si confirmar",
        "si confirmo",
        "si correcto",
        "si dale",
        "si esta correcto",
        "si por favor",
        "sigamos",
        "siguiente",
        "va",
    }


def is_payment_options_question(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return any(
        token in normalized
        for token in [
            "que opciones",
            "que medios",
            "medios de pago",
            "formas de pago",
            "como pago",
            "opciones de pago",
        ]
    )


def payment_preference_from_message(message: str) -> str:
    normalized = normalize_text(message)
    if any(token in normalized for token in ["mercado pago", "mercadopago", "mp", "tarjeta", "link de pago"]):
        return "mercado_pago"
    if any(token in normalized for token in ["transferencia", "transfer", "trasferencia"]):
        return "transferencia"
    return ""


def is_checkout_request_message(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return any(
        token in normalized
        for token in [
            "quiero pagar",
            "ir a pagar",
            "pagar",
            "checkout",
            "finalizar compra",
            "terminar compra",
            "comprar ahora",
            "link de pago",
        ]
    )


def is_workflow_status_question(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return any(
        normalized == token or normalized.startswith(token)
        for token in [
            "como voy",
            "como vamos",
            "como va mi pedido",
            "como va",
            "en que vamos",
            "en que voy",
            "donde voy",
            "donde vamos",
            "cual es mi estado",
            "que sigue",
            "donde quedamos",
            "en que quedamos",
        ]
    )


def is_boleta_request(message: str) -> bool:
    normalized = normalize_text(message)
    return any(token in normalized for token in ["boleta", "solo boleta", "sin factura"])


def is_factura_request(message: str) -> bool:
    normalized = normalize_text(message)
    return any(token in normalized for token in ["factura", "facturar", "con factura", "necesito factura"])


def is_address_correction(message: str) -> bool:
    normalized = normalize_text(message)
    return any(
        token in normalized
        for token in [
            "no", "corregir", "cambiar", "modificar", "esa no es", "direccion incorrecta",
            "esa no", "no correcta", "no esa",
        ]
    )


def is_address_confirmation(message: str) -> bool:
    normalized = normalize_text(message)
    return normalized in {
        "si", "si correcta", "si esta correcta", "correcto", "bien", "ok", "dale",
        "confirmo", "confirmar", "confirmada", "si esa es",
    }


def wants_pickup(message: str) -> bool:
    normalized = normalize_text(message)
    return any(token in normalized for token in ["retiro", "pickup", "recoger en tienda", "retiro en tienda"])


def wants_delivery(message: str) -> bool:
    normalized = normalize_text(message)
    return any(
        token in normalized
        for token in ["despacho", "domicilio", "delivery", "envio", "enviar", "enviame", "llevar a casa"]
    )


def is_recipe_request_message(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return any(
        token in normalized
        for token in [
            "receta", "recetario", "cocinar", "cocino", "queque", "torta", "postre",
            "hambre", "desayuno", "desayunar", "almuerzo", "almorzar", "cena", "cenar", "once",
        ]
    )


def extract_invoice_type(message: str) -> str:
    normalized = normalize_text(message)
    if any(token in normalized for token in ["factura", "facturar", "con factura"]):
        return "factura"
    if any(token in normalized for token in ["boleta", "solo boleta", "sin factura"]):
        return "boleta"
    return ""


def extract_rut(message: str) -> str:
    match = re.search(r'\b(\d{1,2}\.?\d{3}\.?\d{3}[-]?[\dkK])\b', message or "")
    if match:
        return match.group(1).strip()
    match = re.search(r'\b(\d{7,8}[-]?[\dkK])\b', message or "")
    if match:
        return match.group(1).strip()
    return ""


def extract_invoice_business_name(message: str) -> str:
    patterns = [
        r"(?:razon social|razon\s+social|nombre empresa|nombre\s+empresa|empresa|sociedad)\s*:?\s*(.+?)(?:,\s*rut|,\s*direccion|$)",
        r"(?:rut|r\.u\.t)\s*:?\s*\d.*?\s+(.+?)(?:,\s*|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message or "", flags=re.IGNORECASE)
        if match:
            candidate = str(match.group(1) or "").strip().rstrip(".,;")
            if candidate:
                return candidate
    return ""


def extract_invoice_address(message: str) -> str:
    patterns = [
        r"(?:direccion fiscal|direccion facturacion|domicilio fiscal|dir factura)\s*:?\s*(.+?)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, message or "", flags=re.IGNORECASE)
        if match:
            candidate = str(match.group(1) or "").strip().rstrip(".,;")
            if candidate:
                return candidate
    return ""


def extract_pickup_location(message: str) -> str:
    normalized = normalize_text(message)
    if not normalized:
        return ""
    patterns = [
        r"(?:retiro en|pickup en|recoger en)\s+(.+)$",
        r"(?:sucursal|tienda|local)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            candidate = str(match.group(1) or "").strip()
            if candidate in {"tienda", "sucursal", "local", "retiro", "pickup"}:
                return ""
            return candidate
    return ""


def extract_address(message: str) -> str:
    raw = (message or "").strip()
    if not raw:
        return ""
    patterns = [
        r"(?:direccion|dir|envio a|despacho a|domicilio en|para|calle|av|avda|pje|pasaje)\s+(.+)$",
        r"^(.+?\d{3,}.*)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            candidate = str(match.group(1) or "").strip().rstrip(".,;")
            if len(candidate) >= 8:
                return candidate
    return ""


def extract_order_lines_from_result_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (
        data.get("items")
        if isinstance(data.get("items"), list)
        else data.get("lines")
        if isinstance(data.get("lines"), list)
        else data.get("order_lines")
        if isinstance(data.get("order_lines"), list)
        else []
    )
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = first_present_string(row, ["name", "product_name", "title", "label"]) or "Producto"
        quantity_raw = row.get("quantity") or row.get("qty") or 1
        try:
            quantity = max(1, int(quantity_raw))
        except (TypeError, ValueError):
            quantity = 1
        normalized.append({"name": name, "quantity": quantity})
    return normalized


def first_present_string(payload: Any, keys: list[str]) -> str:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            nested = first_present_string(value, keys)
            if nested:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = first_present_string(item, keys)
            if nested:
                return nested
    return ""


def extract_widget_cart_change_requests(
    message: str,
    *,
    mode: str,
) -> list[dict[str, Any]]:
    normalized = normalize_text(message)
    if not normalized:
        return []
    if not has_explicit_cart_change_intent(message, mode):
        return []

    segments = [part.strip() for part in re.split(r"\s+(?:y|e|ademas|tambien)\s+", normalized) if part.strip()]
    requests: list[dict[str, Any]] = []
    for segment in segments:
        if mode == "remove":
            cleaned = re.sub(
                r"\b(?:quita|quitame|quitar|saca|sacame|sacar|remueve|remover|elimina|eliminar|borra|borrar|del|de|la|el|los|las|carrito)\b",
                " ",
                segment,
                flags=re.IGNORECASE,
            )
        else:
            cleaned = re.sub(
                r"\b(?:deja|dejame|dejar|solo|solamente|en|con|la|el|los|las|carrito)\b",
                " ",
                segment,
                flags=re.IGNORECASE,
            )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            continue

        quantity = parse_quantity(segment)
        product_query = re.sub(r"^\d+\s+", "", cleaned).strip()
        product_query = re.sub(r"^(un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+", "", product_query).strip()
        if not product_query:
            continue
        requests.append({"quantity": quantity, "product_query": product_query})
    logger.debug("cart_change.extract mode=%s message=%s requests=%s", mode, message, requests)
    return requests


def extract_widget_cart_requests(message: str) -> list[dict[str, Any]]:
    normalized = normalize_text(message)
    if not normalized:
        return []
    if not has_explicit_add_to_cart_intent(message):
        return []

    segments = [part.strip() for part in re.split(r"\s+(?:y|e|ademas|tambien)\s+", normalized) if part.strip()]
    requests: list[dict[str, Any]] = []
    for segment in segments:
        has_add_verb = bool(
            re.search(
                r"\b(?:agrega|agregame|agregar|suma|sumame|sumar|pon|poneme|poner|mete|meteme|anade|llevo|quiero)\b",
                segment,
                flags=re.IGNORECASE,
            )
        )
        cleaned = re.sub(
            r"\b(?:agrega|agregame|agregar|suma|sumame|sumar|pon|poneme|poner|mete|meteme|anade|llevo|quiero|porfa|por favor|al|carrito|el|la|los|las)\b",
            " ",
            segment,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            continue

        quantity = parse_quantity(segment)
        product_query = re.sub(r"^\d+\s+", "", cleaned).strip()
        product_query = re.sub(r"^(un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+", "", product_query).strip()
        if not product_query:
            continue
        requests.append({"quantity": quantity, "product_query": product_query})
    logger.debug("cart.extract message=%s requests=%s", message, requests)
    return requests


def extract_widget_product_lookup_query(message: str) -> str:
    normalized = normalize_text(message)
    if not normalized:
        return ""

    cleaned = re.sub(
        r"\b(?:hola|buenas|buenos dias|buen dia|quiero saber|queria saber|quisiera saber|me gustaria saber|podrias decirme|podrias mostrarme|me muestras|mostrarme|ver|buscar|busco|tienen|tiene|tenes|tenian|tenia|hay|habia|si|si tienen|si hay|si vende|disponible|disponibles|stock|precio|cuesta|por favor|porfa|el|la|los|las|un|una|unos|unas)\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    logger.debug("lookup.extract message=%s cleaned=%s", message, cleaned)
    return cleaned


def extract_widget_add_to_cart(message: str) -> dict[str, Any] | None:
    requests = extract_widget_cart_requests(message)
    return requests[0] if requests else None


def extract_widget_remove_from_cart(message: str) -> dict[str, Any] | None:
    requests = extract_widget_cart_change_requests(message, mode="remove")
    return requests[0] if requests else None


def extract_widget_set_cart_quantity(message: str) -> dict[str, Any] | None:
    requests = extract_widget_cart_change_requests(message, mode="set")
    return requests[0] if requests else None


def cart_requests_from_llm_intent(parsed: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict):
        return []
    if str(parsed.get("intent") or "").strip().lower() not in {"add_to_cart", "remove_from_cart", "set_cart_quantity", "clear_cart"}:
        return []
    items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
    requests: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        quantity_raw = item.get("quantity")
        quantity = int(quantity_raw) if isinstance(quantity_raw, (int, float)) else 1
        quantity = max(1, min(99, quantity))
        if query:
            requests.append({"product_query": query, "quantity": quantity})
    return requests


def product_lookup_queries_from_llm_intent(parsed: dict[str, Any] | None) -> list[str]:
    if not isinstance(parsed, dict):
        return []
    if str(parsed.get("intent") or "").strip().lower() != "product_lookup":
        return []
    queries: list[str] = []
    seen: set[str] = set()
    items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if query and query not in seen:
            seen.add(query)
            queries.append(query)
    fallback_query = str(parsed.get("query") or "").strip()
    if fallback_query and fallback_query not in seen:
        queries.append(fallback_query)
    return queries


def is_remove_from_cart_message(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return any(
        phrase in normalized
        for phrase in [
            "quita ",
            "quitame ",
            "saca ",
            "sacame ",
            "remueve ",
            "elimina ",
            "borra ",
        ]
    )


def is_set_cart_quantity_message(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return any(
        phrase in normalized
        for phrase in [
            "deja solo ",
            "deja en ",
            "deja solo",
            "dejame solo ",
        ]
    )


def is_login_confirmed_message(message: str) -> bool:
    normalized = normalize_text(message)
    return normalized in {
        "ya inicie sesion",
        "ya inicié sesion",
        "ya inicie login",
        "ya hice login",
        "ya me loguee",
        "ya me autentique",
        "ya estoy logueado",
    }


EMAIL_RE = re.compile(r"^[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+$", re.IGNORECASE)


def is_email_message(message: str) -> bool:
    if not message or not message.strip():
        return False
    return bool(EMAIL_RE.match(message.strip()))


def is_checkout_redirect_channel(channel: str | None) -> bool:
    normalized = (channel or "").strip().lower()
    return normalized in {"widget_web", "web", "widget_public"}


def is_whatsapp_reminder_channel(channel: str | None) -> bool:
    return str(channel or "").strip().lower() in {"whatsapp", "widget_whatsapp"}


def looks_like_phone_number(value: str | None) -> bool:
    digits = re.sub(r"\D+", "", str(value or ""))
    return len(digits) >= 8


def reminder_recipient_for_channel(channel: str | None, session_id: str) -> str | None:
    if not is_whatsapp_reminder_channel(channel):
        return None
    clean_session_id = str(session_id or "").strip()
    if not looks_like_phone_number(clean_session_id):
        return None
    return re.sub(r"\D+", "", clean_session_id)


def workflow_state_customer_authenticated(workflow_state: dict[str, str] | None) -> bool:
    raw = str((workflow_state or {}).get("customer_authenticated") or "").strip().lower()
    return raw in {"1", "true", "yes", "si"}


def workflow_state_bool(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "si"}


def canonical_tool_succeeded(result: Any, expected_statuses: set[str] | None = None) -> bool:
    if not isinstance(result, dict) or not result.get("ok"):
        return False
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if data.get("ok") is True:
        return True
    status = str(data.get("status") or result.get("code") or result.get("status") or "").strip().lower()
    if expected_statuses and status in expected_statuses:
        return True
    return status in {"ok", "sent", "verified", "success", "valid"}


def workflow_action(action_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": action_type, "payload": payload}


def personalize_agent_freeform_response(
    *,
    agent_name: str,
    company_id: str,
    message: str,
    route: str | None,
    default_answer: str,
) -> str:
    return default_answer


def product_lookup_queries_from_message(message: str) -> list[str]:
    normalized = normalize_text(message)
    if not normalized:
        return []
    cleaned = extract_widget_product_lookup_query(message)
    if not cleaned:
        return []
    parts = [part.strip() for part in re.split(r"\s+(?:o|u|y|e)\s+", cleaned) if part.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for part in parts or [cleaned]:
        if len(part) < 2:
            continue
        if part not in seen:
            seen.add(part)
            unique.append(part)
    return unique


def saved_addresses_from_workflow_state(workflow_state: dict[str, str] | None) -> list[dict[str, str]]:
    raw = str((workflow_state or {}).get("saved_addresses") or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, str]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or f"Direccion {index}").strip() or f"Direccion {index}"
        address = str(item.get("address") or item.get("full_address") or item.get("street") or "").strip()
        if not address:
            continue
        rows.append({"label": label, "address": address})
    return rows


def saved_addresses_prompt(addresses: list[dict[str, str]]) -> str:
    lines = [f"{index}. {row['label']}: {row['address']}" for index, row in enumerate(addresses, start=1)]
    return "Puedo usar una de tus direcciones guardadas para la factura:\n" + "\n".join(lines) + "\nDime el numero, el nombre o escribeme una direccion nueva."


def match_saved_address_choice(message: str, addresses: list[dict[str, str]]) -> str:
    normalized = normalize_text(message)
    if not normalized or not addresses:
        return ""
    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(addresses):
            return addresses[index - 1]["address"]
    for row in addresses:
        label = normalize_text(row.get("label") or "")
        address = normalize_text(row.get("address") or "")
        if normalized == label or normalized == address or normalized in label:
            return row["address"]
    return ""
    
    
def parse_iso_datetime(value: str | None) -> datetime | None:
    from datetime import UTC, datetime
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def split_memory_session_id(memory_session_id: str) -> tuple[str, str] | None:
    clean = str(memory_session_id or "").strip()
    if not clean or ":" not in clean:
        return None
    agent_id, session_id = clean.split(":", 1)
    if not agent_id.strip() or not session_id.strip():
        return None
    return agent_id.strip(), session_id.strip()
