from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SessionTurn:
    role: str
    text: str


@dataclass
class SessionSummary:
    user_goal: str = ""
    funnel_stage: str = ""
    checkout_stage: str = ""
    pending_next_step: str = ""
    last_product_query: str = ""
    selected_products: str = ""
    shipping_preference: str = ""
    pickup_location_label: str = ""
    delivery_address: str = ""
    delivery_address_confirmed: bool = False
    invoice_type: str = ""
    invoice_rut: str = ""
    invoice_business_name: str = ""
    invoice_address: str = ""
    payment_preference: str = ""
    customer_authenticated: bool = False
    order_reference: str = ""
    otp_email: str = ""
    last_tool: str = ""
    last_action: str = ""
    notes: str = ""


class SessionStore(Protocol):
    def append_user_message(self, company_id: str, session_id: str, text: str) -> None:
        ...

    def append_assistant_message(self, company_id: str, session_id: str, text: str) -> None:
        ...

    def recent_turns(
        self,
        company_id: str,
        session_id: str,
        limit: int = 4,
    ) -> list[SessionTurn]:
        ...

    def get_summary(self, company_id: str, session_id: str) -> SessionSummary:
        ...

    def save_summary(self, company_id: str, session_id: str, summary: SessionSummary) -> None:
        ...
