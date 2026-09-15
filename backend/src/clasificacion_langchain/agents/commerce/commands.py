from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clasificacion_langchain.agents.commerce.types import StructuredToolName, STRUCTURED_TOOL_NAMES


@dataclass
class CheckoutCommand:
    intent: str
    confidence: float
    requested_tool: StructuredToolName = ""
    needs_clarification: bool = False
    clarification_question: str = ""
    query: str = ""
    customer_goal: str = ""
    product_queries: list[str] = field(default_factory=list)
    quantity: int | None = None
    shipping_method: str = ""
    payment_method: str = ""
    invoice_type: str = ""
    otp_email: str = ""
    otp_code: str = ""
    quantity_only_followup: bool = False
    raw_payload: dict[str, Any] = field(default_factory=dict)


def parse_checkout_command(payload: dict[str, Any] | None) -> CheckoutCommand | None:
    if not isinstance(payload, dict):
        return None
    intent = str(payload.get("intent") or "").strip().lower()
    if not intent:
        return None
    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    requested_tool = str(payload.get("tool") or payload.get("requested_tool") or "").strip().lower()
    if requested_tool not in STRUCTURED_TOOL_NAMES:
        requested_tool = ""
    query = str(payload.get("query") or "").strip()
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    product_queries: list[str] = []
    quantity: int | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        item_query = str(item.get("query") or item.get("product_query") or "").strip()
        if item_query:
            product_queries.append(item_query)
        if quantity is None:
            try:
                parsed_quantity = int(item.get("quantity") or 0)
            except (TypeError, ValueError):
                parsed_quantity = 0
            if parsed_quantity > 0:
                quantity = parsed_quantity
    if not product_queries and query:
        product_queries.append(query)
    quantity_only_followup = bool(query and query.isdigit()) or (quantity is not None and not product_queries)
    return CheckoutCommand(
        intent=intent,
        confidence=max(0.0, min(1.0, confidence)),
        requested_tool=requested_tool,
        needs_clarification=bool(payload.get("needs_clarification")),
        clarification_question=str(payload.get("clarification_question") or "").strip(),
        query=query,
        customer_goal=str(payload.get("customer_goal") or "").strip(),
        product_queries=product_queries,
        quantity=quantity,
        shipping_method=str(((payload.get("tool_arguments") or {}) if isinstance(payload.get("tool_arguments"), dict) else {}).get("shipping_method") or "").strip(),
        payment_method=str(((payload.get("tool_arguments") or {}) if isinstance(payload.get("tool_arguments"), dict) else {}).get("payment_method") or "").strip(),
        invoice_type=str(payload.get("invoice_type") or "").strip(),
        otp_email=str(payload.get("otp_email") or "").strip(),
        otp_code=str(payload.get("otp_code") or "").strip(),
        quantity_only_followup=quantity_only_followup,
        raw_payload=dict(payload),
    )
