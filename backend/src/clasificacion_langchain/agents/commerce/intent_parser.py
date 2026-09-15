from __future__ import annotations

import logging
import re
from typing import Any

from clasificacion_langchain.agents.commerce.extractors import (
    cart_requests_from_llm_intent,
    extract_invoice_address,
    extract_invoice_business_name,
    extract_invoice_type,
    extract_rut,
    is_recipe_request_message,
)
from clasificacion_langchain.agents.commerce.llm_json import call_openai_json
from clasificacion_langchain.agents.commerce.prompting import (
    build_commerce_intent_messages,
    build_invoice_extraction_messages,
    build_recipe_plan_messages,
)
from clasificacion_langchain.agents.commerce.recent_products import (
    normalize_text,
    serialize_recent_products_for_llm,
)

logger = logging.getLogger(__name__)

SUPPORTED_COMMERCE_TOOLS = {
    "get_product_availability",
    "get_order_status",
    "get_shipping_options",
    "get_payment_options",
    "create_payment_link",
    "create_order_draft",
}


def should_try_llm_commerce_parser(intent_label: str | None, message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return True


def parse_commerce_intent_with_openai(
    message: str,
    *,
    session_id: str,
    recent_products: list[dict[str, Any]] | None = None,
    intent_label: str | None = None,
    channel: str | None = None,
    response_style_context: str | None = None,
    workflow_context: str | None = None,
) -> dict[str, Any] | None:
    if not should_try_llm_commerce_parser(intent_label, message):
        return None

    serialized = recent_products if recent_products is not None else []
    try:
        parsed = call_openai_json(
            messages=build_commerce_intent_messages(
                message=message,
                intent_label_hint=intent_label or "",
                channel=channel or "",
                response_style_context=response_style_context or "",
                workflow_context=workflow_context or "",
                recent_products=serialized,
            ),
            temperature=0,
            timeout_seconds=20,
        )
    except Exception as exc:
        logger.warning("commerce_intent_llm_failed session_id=%s detail=%s", session_id, exc)
        return None

    if not isinstance(parsed, dict):
        return None

    logger.info(
        "commerce_intent_llm_ok session_id=%s intent=%s tool=%s confidence=%s query=%s items=%s recent_products=%s",
        session_id,
        parsed.get("intent"),
        parsed.get("tool"),
        parsed.get("confidence"),
        parsed.get("query"),
        parsed.get("items"),
        len(serialized),
    )
    return parsed


def parse_invoice_data_with_openai(
    message: str,
    *,
    session_id: str,
) -> dict[str, Any] | None:
    try:
        parsed = call_openai_json(
            messages=build_invoice_extraction_messages(message),
            temperature=0,
            timeout_seconds=20,
        )
    except Exception as exc:
        logger.warning("invoice_llm_failed session_id=%s detail=%s", session_id, exc)
        return None

    if not isinstance(parsed, dict):
        return None

    logger.info(
        "invoice_llm_ok session_id=%s invoice_type=%s rut=%s business_name=%s address=%s use_delivery=%s",
        session_id,
        parsed.get("invoice_type"),
        parsed.get("rut"),
        parsed.get("business_name"),
        parsed.get("invoice_address"),
        parsed.get("use_delivery_address"),
    )
    return parsed


def extract_invoice_data(
    message: str,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "invoice_type": None,
        "rut": None,
        "business_name": None,
        "invoice_address": None,
        "use_delivery_address": False,
    }

    if session_id:
        llm_result = parse_invoice_data_with_openai(message, session_id=session_id)
        if isinstance(llm_result, dict):
            extracted_any = False
            for key in ("invoice_type", "rut", "business_name", "invoice_address"):
                val = llm_result.get(key)
                if val and str(val).strip():
                    result[key] = str(val).strip()
                    extracted_any = True
            use_delivery = llm_result.get("use_delivery_address")
            if isinstance(use_delivery, bool):
                result["use_delivery_address"] = use_delivery
                extracted_any = extracted_any or use_delivery
            if extracted_any:
                return result

    result["invoice_type"] = extract_invoice_type(message) or None
    result["rut"] = extract_rut(message) or None
    result["business_name"] = extract_invoice_business_name(message) or None
    result["invoice_address"] = extract_invoice_address(message) or None
    return result


def generate_recipe_plan_with_openai(message: str, session_id: str, recent_products: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not is_recipe_request_message(message):
        return None
    recent_names = [str(item.get("name") or "").strip() for item in recent_products if isinstance(item, dict)]

    try:
        parsed = call_openai_json(
            messages=build_recipe_plan_messages(
                message=message,
                recent_product_names=recent_names,
            ),
            temperature=0.2,
            timeout_seconds=25,
        )
    except Exception as exc:
        logger.warning("recipe_plan_llm_failed session_id=%s detail=%s", session_id, exc)
        return None

    if not isinstance(parsed, dict):
        return None
    logger.info("recipe_plan_llm_ok session_id=%s payload=%s", session_id, parsed)
    return parsed


def tool_from_llm_commerce_intent(parsed: dict[str, Any] | None, session_id: str) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(parsed, dict):
        return None
    intent = str(parsed.get("intent") or "").strip().lower()
    confidence_raw = parsed.get("confidence")
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
    if confidence < 0.72:
        return None

    query = str(parsed.get("query") or "").strip()
    planned_tool = str(parsed.get("tool") or "").strip().lower()
    tool_arguments = parsed.get("tool_arguments") if isinstance(parsed.get("tool_arguments"), dict) else {}
    items = cart_requests_from_llm_intent(parsed)

    if planned_tool in SUPPORTED_COMMERCE_TOOLS:
        arguments = dict(tool_arguments)
        arguments.setdefault("session_id", session_id)
        if planned_tool == "get_product_availability" and not arguments.get("query") and query:
            arguments["query"] = query
        if planned_tool == "get_product_availability":
            arguments.setdefault("limit", 5)
        if planned_tool == "get_shipping_options" and "commune" not in arguments:
            arguments["commune"] = query or ""
        if planned_tool == "get_order_status":
            order_reference = str(parsed.get("order_reference") or query or "").strip()
            if order_reference:
                arguments.setdefault("order_reference", order_reference)
                arguments.setdefault("query", order_reference)
        return planned_tool, arguments

    if intent == "add_to_cart" and items:
        first = items[0]
        return "get_product_availability", {"query": first["product_query"], "limit": 5, "session_id": session_id}
    if intent == "product_lookup" and query:
        return "get_product_availability", {"query": query, "limit": 5, "session_id": session_id}
    if intent == "shipping_options":
        return "get_shipping_options", {"commune": query or "", "session_id": session_id}
    if intent in {"payment_options", "checkout"}:
        return "get_payment_options", {"session_id": session_id}
    return None


def selected_product_requests_from_workflow_state(workflow_state: dict[str, str] | None) -> list[dict[str, Any]]:
    raw = str((workflow_state or {}).get("selected_products") or "").strip()
    if not raw:
        return []
    candidates: list[str] = []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    for chunk in re.split(r"[,\n;•]+", raw):
        cleaned = chunk.strip().strip("'\"")
        if cleaned:
            candidates.append(cleaned)
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_text(candidate)
        if key and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return [{"product_query": name, "quantity": 1} for name in unique[:6]]


def checkout_requests_for_workflow(
    message: str,
    session_id: str,
    parsed: dict[str, Any] | None,
    workflow_state: dict[str, str] | None = None,
    recent_products: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    requests = cart_requests_from_llm_intent(parsed)
    if requests:
        return requests
    workflow_requests = selected_product_requests_from_workflow_state(workflow_state)
    if workflow_requests:
        return workflow_requests
    if recent_products:
        return [
            {"product_query": str(product.get("name") or "").strip(), "quantity": 1}
            for product in recent_products[:3]
            if str(product.get("name") or "").strip()
        ]
    return []
