from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import UTC, datetime
from typing import Any

from clasificacion_langchain.chat.session_store import SessionSummary
from clasificacion_langchain.agents.commerce import resume_timeout
from clasificacion_langchain.agents.commerce.intent_parser import (
    selected_product_requests_from_workflow_state,
)
from clasificacion_langchain.agents.commerce.persistence import (
    CheckoutSessionSummaryAdapter,
)
from clasificacion_langchain.agents.commerce.recent_products import (
    is_implicit_add_to_cart_message,
    is_quantity_only_followup,
    match_recent_product_from_message as _recent_product_match,
    normalize_text,
    parse_quantity,
    serialize_recent_products_for_llm,
)
from clasificacion_langchain.agents.commerce.widget_payload import (
    build_multi_cart_tool_payload,
)

logger = logging.getLogger(__name__)

COMMERCE_CONTEXT_LOCK = threading.Lock()
COMMERCE_PRODUCT_CONTEXT: dict[str, dict[str, Any]] = {}
WORKFLOW_EXPIRATION_SECONDS = 1800  # 30 min sin actividad antes de preguntar "seguimos?"
WORKFLOW_RESET_CONFIRMATION_SECONDS = 86400  # 24h de margen para retomar antes de reiniciar de cero

GREETING_TERMS = {
    "hola",
    "buenas",
    "buen dia",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "holi",
    "hello",
    "hi",
}


def is_checkout_langgraph_enabled() -> bool:
    raw = os.getenv("WHATSAPP_CHECKOUT_LANGGRAPH_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def is_likely_greeting_message(message: str) -> bool:
    normalized = normalize_text(message)
    return normalized in GREETING_TERMS


def trace_route(event: str, **payload: Any) -> None:
    safe_payload = {key: value for key, value in payload.items()}
    print(f"[TRACE_ROUTE] {event} {json.dumps(safe_payload, ensure_ascii=False, default=str)}", flush=True)


def log_generated_response(
    *,
    source: str,
    request_id: str | None,
    agent_id: str,
    company_id: str,
    session_id: str,
    channel: str,
    answer: str,
    intent_label: str | None = None,
    route: str | None = None,
    response_mode: str | None = None,
) -> None:
    clean_answer = re.sub(r"\s+", " ", str(answer or "")).strip()
    logger.info(
        (
            "generated_response source=%s request_id=%s agent_id=%s company_id=%s "
            "session_id=%s channel=%s intent=%s route=%s response_mode=%s answer=%s"
        ),
        source,
        request_id or "",
        agent_id,
        company_id,
        session_id,
        channel,
        str(intent_label or ""),
        str(route or ""),
        str(response_mode or ""),
        clean_answer[:500],
    )


def summary_has_active_workflow(summary: SessionSummary) -> bool:
    return any(
        str(value or "").strip()
        for value in [
            summary.funnel_stage,
            summary.checkout_stage,
            summary.pending_next_step,
            summary.awaiting_slot,
            summary.selected_products,
            summary.focused_product,
            summary.shipping_preference,
            summary.pickup_location_label,
            summary.delivery_address,
            summary.invoice_type,
            summary.payment_preference,
            summary.otp_email,
        ]
    ) or bool(summary.customer_authenticated)


def workflow_state_has_active_checkout(workflow_state: dict[str, str] | None) -> bool:
    return resume_timeout.workflow_state_has_active_checkout(workflow_state)


def remember_commerce_products(session_id: str, products: list[dict[str, Any]]) -> None:
    clean_session_id = str(session_id or "").strip()
    if not clean_session_id or not products:
        return
    safe_products = [item for item in products if isinstance(item, dict)][:6]
    if not safe_products:
        return
    with COMMERCE_CONTEXT_LOCK:
        COMMERCE_PRODUCT_CONTEXT[clean_session_id] = {
            "products": safe_products,
            "updated_at": time.time(),
        }


def remember_pending_cart_quantity(session_id: str, quantity: int) -> None:
    """Cantidad pedida antes de elegir variante ("agregame 2 X" -> opciones -> "la segunda")."""
    clean_session_id = str(session_id or "").strip()
    if not clean_session_id:
        return
    with COMMERCE_CONTEXT_LOCK:
        payload = COMMERCE_PRODUCT_CONTEXT.setdefault(clean_session_id, {"products": [], "updated_at": time.time()})
        payload["pending_quantity"] = max(1, int(quantity or 1))
        payload["updated_at"] = time.time()


def pop_pending_cart_quantity(session_id: str) -> int | None:
    clean_session_id = str(session_id or "").strip()
    if not clean_session_id:
        return None
    with COMMERCE_CONTEXT_LOCK:
        payload = COMMERCE_PRODUCT_CONTEXT.get(clean_session_id)
        if not isinstance(payload, dict):
            return None
        value = payload.pop("pending_quantity", None)
    return int(value) if isinstance(value, int) else None


def recent_commerce_products(session_id: str, max_age_seconds: int = 900) -> list[dict[str, Any]]:
    clean_session_id = str(session_id or "").strip()
    if not clean_session_id:
        return []
    with COMMERCE_CONTEXT_LOCK:
        payload = COMMERCE_PRODUCT_CONTEXT.get(clean_session_id)
        if not isinstance(payload, dict):
            return []
        updated_at = payload.get("updated_at")
        if not isinstance(updated_at, (int, float)) or time.time() - float(updated_at) > max_age_seconds:
            COMMERCE_PRODUCT_CONTEXT.pop(clean_session_id, None)
            return []
        products = payload.get("products") if isinstance(payload.get("products"), list) else []
        return [item for item in products if isinstance(item, dict)]


def match_recent_product_from_message(message: str, session_id: str) -> dict[str, Any] | None:
    products = recent_commerce_products(session_id)
    if not products:
        return None
    return _recent_product_match(message, products)


def resolve_focused_product_context(
    message: str, workflow_state: dict[str, str] | None, session_id: str
) -> tuple[str, str] | None:
    focused_product = str((workflow_state or {}).get("focused_product") or "").strip()
    if focused_product:
        return focused_product, focused_product

    selected_products = selected_product_requests_from_workflow_state(workflow_state)
    if selected_products:
        selected_name = str(selected_products[0].get("product_query") or "").strip()
        if selected_name:
            return selected_name, selected_name

    matched_product = match_recent_product_from_message(message, session_id)
    if isinstance(matched_product, dict):
        product_name = str(matched_product.get("name") or "").strip()
        if product_name:
            return product_name, product_name
    recent_products = recent_commerce_products(session_id)
    if recent_products:
        first_name = str(recent_products[0].get("name") or "").strip()
        if first_name:
            return first_name, first_name
    return None


def resolve_quantity_or_action_followup(
    *,
    company_id: str,
    user_id: str,
    channel: str,
    message: str,
    session_id: str,
    workflow_state: dict[str, str] | None,
    clubhx_tools_client: Any,
) -> dict[str, Any] | None:
    awaiting_slot = str((workflow_state or {}).get("awaiting_slot") or "").strip().lower()
    pending_next_step = str((workflow_state or {}).get("pending_next_step") or "").strip().lower()
    workflow_stage = str((workflow_state or {}).get("stage") or "").strip().lower()
    if awaiting_slot != "quantity_or_action" and pending_next_step != "add_to_cart" and workflow_stage != "product_lookup":
        return None

    resolved = resolve_focused_product_context(message, workflow_state, session_id)
    if resolved is None:
        return None
    product_query, focused_product = resolved
    normalized_message = normalize_text(message)
    should_add = (
        is_implicit_add_to_cart_message(message)
        or is_quantity_only_followup(message)
        or bool(match_recent_product_from_message(message, session_id))
        or normalized_message == normalize_text(focused_product)
        or normalized_message == f"el {normalize_text(focused_product)}"
        or normalized_message == f"la {normalize_text(focused_product)}"
    )
    if not should_add:
        return None

    quantity = parse_quantity(message)
    cart_request = {"product_query": product_query, "quantity": quantity}
    try:
        canonical_result = clubhx_tools_client.execute_canonical(
            tenant_id=company_id,
            tool="get_product_availability",
            channel=channel,
            user_id=user_id,
            arguments={
                "query": product_query,
                "limit": 5,
                "session_id": session_id,
            },
        )
    except Exception as exc:
        logger.warning(
            "commerce_quantity_followup_lookup_failed session_id=%s query=%s detail=%s",
            session_id,
            product_query,
            exc,
        )
        return None

    payload = build_multi_cart_tool_payload([canonical_result], [cart_request])
    if isinstance(payload, dict):
        payload["focused_product"] = focused_product
        payload["awaiting_slot"] = "shipping_method"
    return payload


def recent_products_for_llm(session_id: str) -> list[dict[str, Any]]:
    return serialize_recent_products_for_llm(recent_commerce_products(session_id))


def agent_summary_context(
    company_id: str, agent_id: str, session_id: str, agent_service: Any | None
) -> str:
    if agent_service is None or not session_id:
        return ""
    try:
        return agent_service.get_session_summary_text(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
        )
    except Exception as exc:
        logger.warning(
            "agent_summary_context_failed agent_id=%s company_id=%s session_id=%s detail=%s",
            agent_id,
            company_id,
            session_id,
            exc,
        )
        return ""


def agent_workflow_state(
    company_id: str, agent_id: str, session_id: str, agent_service: Any | None
) -> dict[str, str]:
    if agent_service is None or not session_id:
        return {}
    try:
        summary = agent_service.get_session_summary(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
        )
        summary_updated_at = str(getattr(summary, "updated_at", "") or "").strip()
        workflow_reset_started_at = str(getattr(summary, "workflow_reset_started_at", "") or "").strip()
        has_active_workflow = any(
            str(value or "").strip()
            for value in [
                summary.funnel_stage,
                summary.checkout_stage,
                summary.pending_next_step,
                summary.awaiting_slot,
                summary.selected_products,
                summary.focused_product,
                summary.shipping_preference,
                summary.pickup_location_label,
                summary.delivery_address,
                summary.invoice_type,
                summary.payment_preference,
                summary.otp_email,
            ]
        ) or bool(summary.customer_authenticated)
        inactivity_seconds: float | None = None
        if has_active_workflow and summary_updated_at:
            try:
                updated_at = datetime.fromisoformat(summary_updated_at)
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=UTC)
                inactivity_seconds = (datetime.now(UTC) - updated_at).total_seconds()
            except (ValueError, TypeError):
                inactivity_seconds = None
        if has_active_workflow and inactivity_seconds is not None and inactivity_seconds > (WORKFLOW_EXPIRATION_SECONDS + WORKFLOW_RESET_CONFIRMATION_SECONDS):
            agent_service.update_session_summary(
                company_id=company_id,
                agent_id=agent_id,
                session_id=session_id,
                reset_workflow=True,
            )
            return {"workflow_expired": "true"}
        if has_active_workflow and workflow_reset_started_at:
            try:
                reset_started_at = datetime.fromisoformat(workflow_reset_started_at)
                if reset_started_at.tzinfo is None:
                    reset_started_at = reset_started_at.replace(tzinfo=UTC)
                if (datetime.now(UTC) - reset_started_at).total_seconds() > WORKFLOW_RESET_CONFIRMATION_SECONDS:
                    agent_service.update_session_summary(
                        company_id=company_id,
                        agent_id=agent_id,
                        session_id=session_id,
                        reset_workflow=True,
                    )
                    return {"workflow_expired": "true"}
            except (ValueError, TypeError):
                pass
        if has_active_workflow and inactivity_seconds is not None and inactivity_seconds > WORKFLOW_EXPIRATION_SECONDS and not workflow_reset_started_at:
            reset_now = datetime.now(UTC).isoformat()
            agent_service.update_session_summary(
                company_id=company_id,
                agent_id=agent_id,
                session_id=session_id,
                workflow_reset_started_at=reset_now,
            )
            workflow_reset_started_at = reset_now
        customer_authenticated = summary.customer_authenticated
        if customer_authenticated and summary.authenticated_at:
            try:
                authed_at = datetime.fromisoformat(summary.authenticated_at)
                if (datetime.now(UTC) - authed_at).total_seconds() > 900:
                    customer_authenticated = False
            except (ValueError, TypeError):
                pass
        trace_route(
            "workflow_state.read",
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
            stage=summary.funnel_stage,
            checkout_stage=summary.checkout_stage,
            pending_next_step=summary.pending_next_step,
            awaiting_slot=summary.awaiting_slot,
            selected_products=summary.selected_products,
            focused_product=summary.focused_product,
            shipping_preference=summary.shipping_preference,
            payment_preference=summary.payment_preference,
            invoice_type=summary.invoice_type,
            invoice_address=summary.invoice_address,
            saved_addresses=summary.saved_addresses,
            authenticated=customer_authenticated,
        )
        checkout_state = CheckoutSessionSummaryAdapter.from_summary(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
            channel=summary.last_channel or "",
            summary=summary,
        )
        payload = CheckoutSessionSummaryAdapter.to_workflow_state_dict(checkout_state)
        payload["customer_authenticated"] = "true" if customer_authenticated else ""
        payload["updated_at"] = summary_updated_at
        payload["workflow_reset_started_at"] = workflow_reset_started_at
        payload["workflow_timeout_confirmation"] = "true" if workflow_reset_started_at else ""
        return payload
    except Exception as exc:
        logger.warning(
            "agent_workflow_state_failed agent_id=%s company_id=%s session_id=%s detail=%s",
            agent_id,
            company_id,
            session_id,
            exc,
        )
        return {}
