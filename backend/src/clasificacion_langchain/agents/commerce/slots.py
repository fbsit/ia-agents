from __future__ import annotations

from dataclasses import dataclass, field

from clasificacion_langchain.agents.commerce.commands import CheckoutCommand
from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState, normalize_awaiting_slot


@dataclass
class SlotResolution:
    missing: list[str] = field(default_factory=list)


def align_command_to_stage(
    state: WhatsAppCheckoutState,
    command: CheckoutCommand | None,
) -> CheckoutCommand | None:
    if command is None:
        return None
    if state.checkout_stage == "document_type_pending" or state.pending_next_step == "document_type":
        invoice_type = state.invoice_type or command.invoice_type
        if invoice_type:
            command.intent = "document_type_select"
            command.invoice_type = invoice_type
            command.requested_tool = ""
            command.needs_clarification = False
            command.clarification_question = ""
    if state.checkout_stage == "order_summary_pending" or state.pending_next_step == "order_confirmation":
        command.intent = "order_confirm"
        command.requested_tool = ""
        command.needs_clarification = False
        command.clarification_question = ""
    if state.pending_next_step == "add_to_cart" and command.quantity_only_followup:
        command.intent = "add_to_cart"
        command.requested_tool = ""
    return command


def merge_command_into_state(
    state: WhatsAppCheckoutState,
    command: CheckoutCommand | None,
) -> WhatsAppCheckoutState:
    if command is None:
        return state
    if command.customer_goal and not state.user_goal:
        state.user_goal = command.customer_goal
    if command.product_queries and not state.selected_products:
        state.selected_products = [item for item in command.product_queries if item]
    if command.product_queries and not state.focused_product:
        state.focused_product = command.product_queries[0]
    if command.shipping_method and not state.shipping_preference:
        state.shipping_preference = command.shipping_method
    if command.payment_method and not state.payment_preference:
        state.payment_preference = command.payment_method
    if command.invoice_type and not state.invoice_type:
        state.invoice_type = command.invoice_type
    if command.otp_email and not state.otp_email:
        state.otp_email = command.otp_email
    if state.awaiting_slot:
        state.awaiting_slot = normalize_awaiting_slot(state.awaiting_slot)
    return state


def resolve_missing_slots(state: WhatsAppCheckoutState) -> SlotResolution:
    missing: list[str] = []
    awaiting_slot = state.awaiting_slot
    if awaiting_slot in {"quantity_or_action", "product_quantity"} and not state.focused_product:
        missing.append("product")
    if awaiting_slot == "shipping_method" and not state.shipping_preference:
        missing.append("shipping_method")
    if awaiting_slot == "payment_method" and not state.payment_preference:
        missing.append("payment_method")
    if awaiting_slot == "document_type" and not state.invoice_type:
        missing.append("document_type")
    if awaiting_slot == "invoice_address" and not state.invoice_address:
        missing.append("invoice_address")
    if awaiting_slot == "otp_email" and not state.otp_email:
        missing.append("otp_email")
    return SlotResolution(missing=missing)
