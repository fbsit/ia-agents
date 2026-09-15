from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clasificacion_langchain.agents.commerce.types import AwaitingSlot, CheckoutStage


def normalize_stage(value: str | None) -> CheckoutStage:
    raw = str(value or "").strip().lower()
    aliases: dict[str, CheckoutStage] = {
        "": "browsing",
        "product_lookup": "product_discovery",
        "cart_building": "cart_management",
        "checkout_ready": "order_review",
        "shipping_selection": "shipping_selection",
        "payment_selection": "payment_selection",
        "browsing": "browsing",
        "post_sale_support": "post_sale_support",
        "human_handoff": "human_handoff",
        "checkout_auth": "checkout_auth",
        "document_selection": "document_selection",
        "order_review": "order_review",
        "payment_execution": "payment_execution",
        "completed": "completed",
    }
    return aliases.get(raw, "browsing")


def normalize_awaiting_slot(value: str | None) -> AwaitingSlot:
    raw = str(value or "").strip().lower()
    aliases: dict[str, AwaitingSlot] = {
        "": "",
        "quantity_or_action": "quantity_or_action",
        "shipping_method": "shipping_method",
        "payment_method": "payment_method",
        "document_type": "document_type",
        "invoice_address": "invoice_address",
        "otp_verification": "otp_code",
        "otp_code": "otp_code",
        "otp_email": "otp_email",
        "delivery_address": "delivery_address",
        "pickup_location": "pickup_location",
        "invoice_data": "invoice_data",
        "product_quantity": "product_quantity",
    }
    return aliases.get(raw, "")


def _legacy_stage(stage: CheckoutStage) -> str:
    mapping = {
        "product_discovery": "product_lookup",
        "cart_management": "cart_building",
        "order_review": "checkout_ready",
    }
    return mapping.get(stage, stage)


@dataclass
class WhatsAppCheckoutState:
    company_id: str
    agent_id: str
    session_id: str
    channel: str
    user_id: str = ""
    stage: CheckoutStage = "browsing"
    checkout_stage: str = ""
    pending_next_step: str = ""
    awaiting_slot: AwaitingSlot = ""
    user_goal: str = ""
    selected_products: list[str] = field(default_factory=list)
    focused_product: str = ""
    cart_snapshot: str = ""
    shipping_preference: str = ""
    pickup_location_label: str = ""
    delivery_address: str = ""
    delivery_address_confirmed: bool = False
    payment_preference: str = ""
    invoice_type: str = ""
    invoice_rut: str = ""
    invoice_business_name: str = ""
    invoice_address: str = ""
    customer_authenticated: bool = False
    otp_email: str = ""
    authenticated_at: str = ""
    order_reference: str = ""
    saved_addresses: str = ""
    notes: str = ""
    reminder_recipient: str = ""
    workflow_reset_started_at: str = ""
    workflow_timeout_confirmation: bool = False
    workflow_expired: bool = False

    @property
    def has_selected_products(self) -> bool:
        return bool(self.selected_products)

    @property
    def invoice_data_complete(self) -> bool:
        if self.invoice_type.strip().lower() != "factura":
            return True
        return bool(self.invoice_rut.strip()) and bool(self.invoice_business_name.strip())

    @property
    def has_timeout_reset_markers(self) -> bool:
        return bool(self.workflow_timeout_confirmation or self.workflow_expired or self.workflow_reset_started_at)

    @property
    def has_active_workflow(self) -> bool:
        return any(
            [
                self.stage,
                self.checkout_stage,
                self.pending_next_step,
                self.awaiting_slot,
                self.shipping_preference,
                self.payment_preference,
                self.pickup_location_label,
                self.delivery_address,
                self.invoice_type,
                self.otp_email,
            ]
        ) or self.customer_authenticated

    def to_workflow_state_dict(self) -> dict[str, str]:
        return {
            "stage": _legacy_stage(self.stage),
            "checkout_stage": self.checkout_stage,
            "pending_next_step": self.pending_next_step,
            "awaiting_slot": self.awaiting_slot,
            "selected_products": ", ".join(self.selected_products),
            "focused_product": self.focused_product,
            "cart_snapshot": self.cart_snapshot,
            "shipping_preference": self.shipping_preference,
            "pickup_location_label": self.pickup_location_label,
            "delivery_address": self.delivery_address,
            "delivery_address_confirmed": "true" if self.delivery_address_confirmed else "",
            "invoice_type": self.invoice_type,
            "invoice_rut": self.invoice_rut,
            "invoice_business_name": self.invoice_business_name,
            "invoice_address": self.invoice_address,
            "payment_preference": self.payment_preference,
            "saved_addresses": self.saved_addresses,
            "customer_authenticated": "true" if self.customer_authenticated else "",
            "order_reference": self.order_reference,
            "otp_email": self.otp_email,
            "authenticated_at": self.authenticated_at,
            "workflow_reset_started_at": self.workflow_reset_started_at,
            "workflow_timeout_confirmation": "true" if self.workflow_timeout_confirmation else "",
            "workflow_expired": "true" if self.workflow_expired else "",
        }


def coerce_workflow_state(
    *,
    company_id: str,
    agent_id: str,
    session_id: str,
    channel: str,
    workflow_state: dict[str, str] | None,
    user_id: str = "",
) -> WhatsAppCheckoutState:
    source = workflow_state or {}
    selected_products = [
        item.strip()
        for item in str(source.get("selected_products") or "").split(",")
        if item.strip()
    ]
    return WhatsAppCheckoutState(
        company_id=company_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=user_id,
        channel=channel,
        stage=normalize_stage(source.get("stage")),
        checkout_stage=str(source.get("checkout_stage") or "").strip(),
        pending_next_step=str(source.get("pending_next_step") or "").strip(),
        awaiting_slot=normalize_awaiting_slot(source.get("awaiting_slot")),
        selected_products=selected_products,
        focused_product=str(source.get("focused_product") or "").strip(),
        cart_snapshot=str(source.get("cart_snapshot") or "").strip(),
        shipping_preference=str(source.get("shipping_preference") or "").strip(),
        pickup_location_label=str(source.get("pickup_location_label") or "").strip(),
        delivery_address=str(source.get("delivery_address") or "").strip(),
        delivery_address_confirmed=str(source.get("delivery_address_confirmed") or "").strip().lower() in {"1", "true", "yes", "si"},
        payment_preference=str(source.get("payment_preference") or "").strip(),
        invoice_type=str(source.get("invoice_type") or "").strip(),
        invoice_rut=str(source.get("invoice_rut") or "").strip(),
        invoice_business_name=str(source.get("invoice_business_name") or "").strip(),
        invoice_address=str(source.get("invoice_address") or "").strip(),
        customer_authenticated=str(source.get("customer_authenticated") or "").strip().lower() in {"1", "true", "yes", "si"},
        otp_email=str(source.get("otp_email") or "").strip(),
        authenticated_at=str(source.get("authenticated_at") or "").strip(),
        order_reference=str(source.get("order_reference") or "").strip(),
        saved_addresses=str(source.get("saved_addresses") or "").strip(),
        workflow_reset_started_at=str(source.get("workflow_reset_started_at") or "").strip(),
        workflow_timeout_confirmation=str(source.get("workflow_timeout_confirmation") or "").strip().lower() in {"1", "true", "yes", "si"},
        workflow_expired=str(source.get("workflow_expired") or "").strip().lower() in {"1", "true", "yes", "si"},
    )


def state_to_legacy_workflow_dict(state: WhatsAppCheckoutState) -> dict[str, str]:
    return state.to_workflow_state_dict()


def apply_payload_state(
    state: WhatsAppCheckoutState,
    payload: dict[str, Any] | None,
) -> WhatsAppCheckoutState:
    if not isinstance(payload, dict):
        return state
    next_state = coerce_workflow_state(
        company_id=state.company_id,
        agent_id=state.agent_id,
        session_id=state.session_id,
        channel=state.channel,
        workflow_state={
            **state.to_workflow_state_dict(),
            "stage": str(payload.get("workflow_stage") or state.stage),
            "checkout_stage": str(payload.get("checkout_stage") or state.checkout_stage),
            "pending_next_step": str(payload.get("pending_next_step") or state.pending_next_step),
            "awaiting_slot": str(payload.get("awaiting_slot") or state.awaiting_slot),
            "payment_preference": str(payload.get("payment_preference") or state.payment_preference),
            "otp_email": str(payload.get("otp_email") or state.otp_email),
        },
    )
    if isinstance(payload.get("products"), list):
        next_state.selected_products = [
            str(item.get("name") or "").strip()
            for item in payload.get("products")
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
    return next_state
