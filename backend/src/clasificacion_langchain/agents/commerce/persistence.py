from __future__ import annotations

from dataclasses import replace

from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState, coerce_workflow_state, state_to_legacy_workflow_dict
from clasificacion_langchain.chat.session_store import SessionSummary


class CheckoutSessionSummaryAdapter:
    # Phase-one persistence strategy: keep SessionSummary as the storage contract
    # and project it into the typed workflow state instead of introducing a new store.
    @staticmethod
    def from_summary(
        *,
        company_id: str,
        agent_id: str,
        session_id: str,
        channel: str,
        summary: SessionSummary,
    ) -> WhatsAppCheckoutState:
        return coerce_workflow_state(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
            channel=channel,
            workflow_state={
                "stage": summary.funnel_stage,
                "checkout_stage": summary.checkout_stage,
                "pending_next_step": summary.pending_next_step,
                "awaiting_slot": summary.awaiting_slot,
                "selected_products": summary.selected_products,
                "focused_product": summary.focused_product,
                "cart_snapshot": summary.cart_snapshot,
                "shipping_preference": summary.shipping_preference,
                "pickup_location_label": summary.pickup_location_label,
                "delivery_address": summary.delivery_address,
                "delivery_address_confirmed": "true" if summary.delivery_address_confirmed else "",
                "invoice_type": summary.invoice_type,
                "invoice_rut": summary.invoice_rut,
                "invoice_business_name": summary.invoice_business_name,
                "invoice_address": summary.invoice_address,
                "payment_preference": summary.payment_preference,
                "saved_addresses": summary.saved_addresses,
                "customer_authenticated": "true" if summary.customer_authenticated else "",
                "order_reference": summary.order_reference,
                "otp_email": summary.otp_email,
                "authenticated_at": summary.authenticated_at,
                "workflow_reset_started_at": summary.workflow_reset_started_at,
            },
        )

    @staticmethod
    def to_summary(summary: SessionSummary, state: WhatsAppCheckoutState) -> SessionSummary:
        next_summary = replace(summary)
        next_summary.funnel_stage = state.stage
        next_summary.checkout_stage = state.checkout_stage
        next_summary.pending_next_step = state.pending_next_step
        next_summary.awaiting_slot = state.awaiting_slot
        next_summary.selected_products = ", ".join(state.selected_products)
        next_summary.focused_product = state.focused_product
        next_summary.cart_snapshot = state.cart_snapshot
        next_summary.shipping_preference = state.shipping_preference
        next_summary.pickup_location_label = state.pickup_location_label
        next_summary.delivery_address = state.delivery_address
        next_summary.delivery_address_confirmed = state.delivery_address_confirmed
        next_summary.invoice_type = state.invoice_type
        next_summary.invoice_rut = state.invoice_rut
        next_summary.invoice_business_name = state.invoice_business_name
        next_summary.invoice_address = state.invoice_address
        next_summary.payment_preference = state.payment_preference
        next_summary.saved_addresses = state.saved_addresses
        next_summary.customer_authenticated = state.customer_authenticated
        next_summary.order_reference = state.order_reference
        next_summary.otp_email = state.otp_email
        next_summary.authenticated_at = state.authenticated_at
        next_summary.workflow_reset_started_at = state.workflow_reset_started_at
        next_summary.reminder_recipient = state.reminder_recipient
        next_summary.notes = state.notes or next_summary.notes
        return next_summary

    @staticmethod
    def to_workflow_state_dict(state: WhatsAppCheckoutState) -> dict[str, str]:
        return state_to_legacy_workflow_dict(state)
