from __future__ import annotations

from dataclasses import dataclass


WORKFLOW_STAGES = {
    "browsing",
    "product_lookup",
    "cart_building",
    "shipping_selection",
    "payment_selection",
    "checkout_ready",
    "post_sale_support",
    "human_handoff",
}


@dataclass
class CommerceWorkflowState:
    stage: str = "browsing"
    has_selected_products: bool = False
    has_shipping_preference: bool = False
    has_payment_preference: bool = False
    has_order_reference: bool = False


@dataclass
class CommerceTransitionDecision:
    allowed: bool
    next_stage: str
    clarification: str = ""
    notes: str = ""


def normalize_stage(stage: str | None) -> str:
    candidate = (stage or "").strip().lower()
    if candidate in WORKFLOW_STAGES:
        return candidate
    return "browsing"


def build_state(
    *,
    stage: str | None,
    selected_products: str | None,
    shipping_preference: str | None,
    payment_preference: str | None,
    order_reference: str | None,
) -> CommerceWorkflowState:
    return CommerceWorkflowState(
        stage=normalize_stage(stage),
        has_selected_products=bool((selected_products or "").strip()),
        has_shipping_preference=bool((shipping_preference or "").strip()),
        has_payment_preference=bool((payment_preference or "").strip()),
        has_order_reference=bool((order_reference or "").strip()),
    )


def resolve_transition(
    *,
    current: CommerceWorkflowState,
    intent_label: str | None,
    tool_name: str | None,
) -> CommerceTransitionDecision:
    intent = (intent_label or "").strip().lower()
    tool = (tool_name or "").strip().lower()
    key = tool or intent

    if key in {"product_lookup", "catalog_query", "availability_check", "get_product_availability"}:
        return CommerceTransitionDecision(True, "product_lookup")

    if key in {"add_to_cart", "cart_add", "cart_update"}:
        if not current.has_selected_products:
            return CommerceTransitionDecision(
                False,
                current.stage,
                "Antes de agregar al carrito necesito confirmar el producto exacto.",
                "missing_product_selection",
            )
        return CommerceTransitionDecision(True, "cart_building")

    if key in {"shipping_options", "delivery_quote", "shipping_select", "get_shipping_options"}:
        if not current.has_selected_products and current.stage == "browsing":
            return CommerceTransitionDecision(
                False,
                current.stage,
                "Primero confirmemos que producto quieres llevar y despues vemos el despacho.",
                "shipping_without_product",
            )
        return CommerceTransitionDecision(True, "shipping_selection")

    if key in {"payment_options", "payment_select", "checkout_payment", "get_payment_options"}:
        if not current.has_selected_products:
            return CommerceTransitionDecision(
                False,
                current.stage,
                "Antes de pasar a pago necesito confirmar que producto o carrito quieres comprar.",
                "payment_without_product",
            )
        return CommerceTransitionDecision(True, "payment_selection")

    if key in {"create_order_draft"}:
        if not current.has_selected_products:
            return CommerceTransitionDecision(
                False,
                current.stage,
                "Para crear la orden necesito que me confirmes el producto y la cantidad.",
                "draft_without_items",
            )
        return CommerceTransitionDecision(True, "checkout_ready")

    if key in {"create_payment_link"}:
        if not current.has_selected_products:
            return CommerceTransitionDecision(
                False,
                current.stage,
                "Para generar el link de pago necesito que me confirmes el producto o carrito a pagar.",
                "payment_link_without_items",
            )
        return CommerceTransitionDecision(True, "checkout_ready")

    if key in {"order_status", "get_order_status"}:
        if not current.has_order_reference:
            return CommerceTransitionDecision(
                False,
                current.stage,
                "Para revisar el estado del pedido necesito el numero de orden o pedido.",
                "order_status_without_reference",
            )
        return CommerceTransitionDecision(True, "post_sale_support")

    if key in {"recipe_recommendation"}:
        return CommerceTransitionDecision(True, "browsing")

    return CommerceTransitionDecision(True, current.stage or "browsing")
