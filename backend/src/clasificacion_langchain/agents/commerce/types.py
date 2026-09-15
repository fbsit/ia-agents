from __future__ import annotations

from typing import Literal, TypeAlias


CheckoutStage: TypeAlias = Literal[
    "browsing",
    "product_discovery",
    "cart_management",
    "checkout_auth",
    "shipping_selection",
    "payment_selection",
    "document_selection",
    "order_review",
    "payment_execution",
    "completed",
    "post_sale_support",
    "human_handoff",
]

AwaitingSlot: TypeAlias = Literal[
    "",
    "product_quantity",
    "quantity_or_action",
    "shipping_method",
    "pickup_location",
    "delivery_address",
    "payment_method",
    "document_type",
    "invoice_data",
    "invoice_address",
    "otp_code",
    "otp_email",
]

WorkflowResultKind: TypeAlias = Literal[
    "none",
    "clarification",
    "tool_call",
    "tool_blocked",
    "response",
]

StructuredToolName: TypeAlias = Literal[
    "",
    "get_product_availability",
    "get_order_status",
    "get_shipping_options",
    "get_payment_options",
    "create_payment_link",
    "create_order",
    "create_order_draft",
    "send_verification_code",
    "verify_verification_code",
]


CHECKOUT_STAGES: tuple[CheckoutStage, ...] = (
    "browsing",
    "product_discovery",
    "cart_management",
    "checkout_auth",
    "shipping_selection",
    "payment_selection",
    "document_selection",
    "order_review",
    "payment_execution",
    "completed",
    "post_sale_support",
    "human_handoff",
)

AWAITING_SLOTS: tuple[AwaitingSlot, ...] = (
    "",
    "product_quantity",
    "quantity_or_action",
    "shipping_method",
    "pickup_location",
    "delivery_address",
    "payment_method",
    "document_type",
    "invoice_data",
    "invoice_address",
    "otp_code",
    "otp_email",
)

STRUCTURED_TOOL_NAMES: tuple[StructuredToolName, ...] = (
    "",
    "get_product_availability",
    "get_order_status",
    "get_shipping_options",
    "get_payment_options",
    "create_payment_link",
    "create_order",
    "create_order_draft",
    "send_verification_code",
    "verify_verification_code",
)
