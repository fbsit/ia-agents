from __future__ import annotations

from dataclasses import dataclass

from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState


@dataclass
class GuardDecision:
    allowed: bool
    reason: str = ""
    clarification: str = ""


def evaluate_tool_guard(
    state: WhatsAppCheckoutState,
    tool_name: str | None,
) -> GuardDecision:
    tool = str(tool_name or "").strip().lower()
    if not tool:
        return GuardDecision(True)
    if tool in {"get_product_availability", "get_shipping_options", "get_payment_options"}:
        return GuardDecision(True)
    if tool == "get_order_status":
        if state.order_reference:
            return GuardDecision(True)
        return GuardDecision(False, "missing_order_reference", "Para revisar el pedido necesito el numero de orden o pedido.")
    if tool in {"create_payment_link", "create_order_draft", "create_order"}:
        if not state.has_selected_products:
            return GuardDecision(False, "missing_products", "Primero confirmemos el producto y la cantidad antes de cerrar el checkout.")
        if not state.customer_authenticated:
            return GuardDecision(False, "auth_required", "Antes de continuar con el pago necesito validar tu acceso.")
        return GuardDecision(True)
    if tool == "verify_verification_code":
        if state.otp_email:
            return GuardDecision(True)
        return GuardDecision(False, "missing_otp_email", "Necesito tu correo antes de validar el codigo.")
    return GuardDecision(True)
