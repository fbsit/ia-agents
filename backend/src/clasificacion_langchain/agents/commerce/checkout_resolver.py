from __future__ import annotations

import logging
from typing import Any

from clasificacion_langchain.agents.commerce.extractors import (
    is_affirmative_followup_message,
    is_checkout_request_message,
    is_payment_options_question,
    payment_preference_from_message,
)
from clasificacion_langchain.agents.commerce.intent_parser import (
    checkout_requests_for_workflow,
)
from clasificacion_langchain.agents.commerce.response_mapper import (
    build_order_created_answer,
    build_payment_options_answer,
    normalize_catalog_product,
    option_names_from_result,
)
from clasificacion_langchain.agents.commerce.widget_payload import (
    format_public_widget_tool_payload,
)
from clasificacion_langchain.integrations.clubhx import ClubHxToolsClient

logger = logging.getLogger(__name__)


def _workflow_action(action_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": action_type, "payload": payload}


def resolve_checkout_items(
    *,
    company_id: str,
    user_id: str,
    channel: str,
    session_id: str,
    cart_requests: list[dict[str, Any]],
    clubhx_tools_client: ClubHxToolsClient,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    canonical_results = [
        clubhx_tools_client.execute_canonical(
            tenant_id=company_id,
            tool="get_product_availability",
            channel=channel,
            user_id=user_id,
            arguments={
                "query": str(cart_request.get("product_query") or "").strip(),
                "limit": 5,
                "session_id": session_id,
            },
        )
        for cart_request in cart_requests
        if str(cart_request.get("product_query") or "").strip()
    ]
    logger.warning(
        "commerce_checkout_resolve cart_requests=%s canonical_results_count=%s",
        cart_requests,
        len(canonical_results),
    )
    items: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    seen_products: set[str] = set()
    for cart_request, result in zip(cart_requests, canonical_results):
        if not isinstance(result, dict) or not result.get("ok"):
            logger.warning(
                "commerce_checkout_skip reason=result_not_ok cart_request=%s result=%s",
                cart_request,
                result.get("ok") if isinstance(result, dict) else type(result).__name__,
            )
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        rows = data.get("items") if isinstance(data.get("items"), list) else []
        safe_rows = [row for row in rows if isinstance(row, dict)]
        if not safe_rows:
            logger.warning(
                "commerce_checkout_skip reason=no_items cart_request=%s",
                cart_request,
            )
            continue
        first = safe_rows[0]
        product_id = str(first.get("id") or "").strip()
        checkout_product_id = str(first.get("code") or first.get("id") or "").strip()
        variant_id = str(first.get("id") or "").strip()
        name = str(first.get("name") or "Producto").strip() or "Producto"
        quantity = int(cart_request.get("quantity") or 1)

        logger.warning(
            "commerce_checkout_raw_item raw_item=%s cart_request=%s",
            {k: first.get(k) for k in ("id", "code", "name", "price", "available_units") if k in first},
            cart_request,
        )

        if not product_id:
            logger.warning(
                "commerce_checkout_skip reason=no_product_id raw_item=%s cart_request=%s",
                {k: first.get(k) for k in ("id", "code", "name") if k in first},
                cart_request,
            )
            continue
        items.append(
            {
                "product_id": checkout_product_id or product_id,
                "checkout_product_id": checkout_product_id or product_id,
                "variant_id": variant_id or product_id,
                "quantity": max(1, min(99, quantity)),
                "name": name,
            }
        )
        for row in safe_rows[:3]:
            row_id = str(row.get("id") or "").strip()
            if not row_id or row_id in seen_products:
                continue
            seen_products.add(row_id)
            products.append(normalize_catalog_product(row))
    return items, products


def resolve_checkout_payment_followup(
    *,
    message: str,
    session_id: str | None,
    workflow_state: dict[str, str] | None,
    company_id: str | None,
    channel: str | None,
    user_id: str | None,
    clubhx_tools_client: Any | None,
) -> dict[str, Any] | None:
    current_checkout_stage = str((workflow_state or {}).get("checkout_stage") or "").strip().lower()
    current_pending_next_step = str((workflow_state or {}).get("pending_next_step") or "").strip().lower()
    if current_pending_next_step != "payment_selection" and current_checkout_stage not in {
        "payment_method_pending",
        "pickup_location_selected",
        "delivery_address_confirmed",
        "order_summary_pending",
    }:
        return None
    if clubhx_tools_client is None:
        return None

    preference = payment_preference_from_message(message)
    if is_payment_options_question(message) or is_checkout_request_message(message) or (not preference and is_affirmative_followup_message(message)):
        try:
            result = clubhx_tools_client.execute_canonical(
                tenant_id=company_id or "",
                tool="get_payment_options",
                channel=channel or "",
                user_id=user_id,
                arguments={"session_id": session_id or ""},
            )
        except Exception as exc:
            logger.warning("checkout_payment_options_failed session_id=%s detail=%s", session_id, exc)
            return None
        return {
            "answer": build_payment_options_answer(option_names_from_result(result)),
            "intent_label": "payment_options",
            "workflow_stage": "payment_selection",
            "checkout_stage": "payment_method_pending",
            "pending_next_step": "payment_selection",
            "awaiting_slot": "payment_method",
            "workflow_action": _workflow_action("choose_payment_method"),
        }

    if not preference:
        return None
    return {
        "answer": f"Perfecto, dejo {message.strip()} como medio de pago. Ahora dime si necesitas boleta o factura.",
        "intent_label": "payment_method_selected",
        "workflow_stage": "payment_selection",
        "checkout_stage": "document_type_pending",
        "pending_next_step": "document_type",
        "awaiting_slot": "document_type",
        "payment_preference": preference,
        "workflow_action": _workflow_action("choose_document_type", payment_preference=preference),
    }


def resolve_checkout_order_confirmation_followup(
    *,
    message: str,
    session_id: str | None,
    workflow_state: dict[str, str] | None,
    company_id: str | None,
    channel: str | None,
    user_id: str | None,
    clubhx_tools_client: Any | None,
    recent_products: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    current_checkout_stage = str((workflow_state or {}).get("checkout_stage") or "").strip().lower()
    current_pending_next_step = str((workflow_state or {}).get("pending_next_step") or "").strip().lower()
    if current_checkout_stage != "order_summary_pending" and current_pending_next_step != "order_confirmation":
        return None
    if not is_affirmative_followup_message(message) or clubhx_tools_client is None:
        return None

    payment_preference = payment_preference_from_message(str((workflow_state or {}).get("payment_preference") or "")) or str((workflow_state or {}).get("payment_preference") or "").strip()
    cart_requests = checkout_requests_for_workflow(message, session_id or "", None, workflow_state, recent_products=recent_products)
    if not cart_requests:
        return {
            "answer": "Primero necesito confirmar los productos del carrito antes de crear la orden.",
            "intent_label": "payment_items_missing",
            "workflow_stage": "cart_building",
            "pending_next_step": "add_to_cart",
            "awaiting_slot": "quantity_or_action",
        }
    checkout_items, checkout_products = resolve_checkout_items(
        company_id=company_id or "",
        user_id=user_id or "",
        channel=channel or "",
        session_id=session_id or "",
        cart_requests=cart_requests,
        clubhx_tools_client=clubhx_tools_client,
    )
    if not checkout_items:
        return {"answer": "No pude validar los productos del pedido. Dime el nombre exacto del producto y la cantidad."}

    try:
        result = clubhx_tools_client.execute_canonical(
            tenant_id=company_id or "",
            tool="create_order_draft",
            channel=channel or "",
            user_id=user_id,
            arguments={
                "items": checkout_items,
                "session_id": session_id or "",
                "payment_preference": payment_preference,
                "invoice_type": str((workflow_state or {}).get("invoice_type") or "").strip(),
                "invoice_rut": str((workflow_state or {}).get("invoice_rut") or "").strip(),
                "invoice_business_name": str((workflow_state or {}).get("invoice_business_name") or "").strip(),
                "invoice_address": str((workflow_state or {}).get("invoice_address") or "").strip(),
                "delivery_address": str((workflow_state or {}).get("delivery_address") or "").strip(),
                "pickup_location_label": str((workflow_state or {}).get("pickup_location_label") or "").strip(),
            },
        )
    except Exception as exc:
        logger.warning("checkout_order_confirmation_failed session_id=%s detail=%s", session_id, exc)
        return None
    payload = format_public_widget_tool_payload(
        result,
        user_message=message,
        intent_label="create_order_draft",
        channel=channel,
        session_id=session_id,
    )
    if isinstance(payload, dict):
        if checkout_products and not payload.get("products"):
            payload["products"] = checkout_products[:6]
        payload["payment_preference"] = payment_preference
        payload["awaiting_slot"] = ""
        result_data = result.get("data") if isinstance(result.get("data"), dict) else {}
        payload["answer"] = build_order_created_answer(
            workflow_state=workflow_state,
            checkout_items=checkout_items,
            result_data=result_data,
        )
        return payload
    return None
