from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.agents.commerce.commands import CheckoutCommand
from clasificacion_langchain.agents.commerce.resolver import CheckoutWorkflowResolver
from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute(self, *, tenant_id: str, tool: str, channel: str, user_id: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((tool, arguments))
        if tool == "get_payment_options":
            return {"ok": True, "data": {"options": [{"name": "Mercado Pago"}, {"name": "Transferencia bancaria"}]}}
        if tool == "send_verification_code":
            return {"ok": True, "data": {"status": "sent"}}
        if tool == "verify_verification_code":
            return {"ok": True, "data": {"status": "verified"}}
        if tool == "create_order":
            return {"ok": True, "data": {"order_reference": "12345", "total": "$10980"}}
        raise AssertionError(tool)


def test_resolver_checkout_continue_requires_auth_then_otp_flow() -> None:
    executor = FakeExecutor()
    resolver = CheckoutWorkflowResolver(executor=executor, fallback=lambda state, command: None)

    checkout_state = WhatsAppCheckoutState(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        channel="whatsapp",
        user_id="user-1",
        stage="cart_management",
        checkout_stage="",
        pending_next_step="",
        selected_products=["Milo"],
        customer_authenticated=False,
    )

    auth_payload = resolver.resolve(
        checkout_state,
        CheckoutCommand(intent="checkout_continue", confidence=0.9),
    )
    assert auth_payload is not None
    assert auth_payload["checkout_stage"] == "auth_pending"

    email_state = WhatsAppCheckoutState(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        channel="whatsapp",
        user_id="user-1",
        stage="checkout_auth",
        checkout_stage="auth_pending",
        pending_next_step="auth_confirmation",
        selected_products=["Milo"],
        customer_authenticated=False,
        user_goal="test@example.com",
    )
    email_payload = resolver.resolve(email_state, CheckoutCommand(intent="checkout_continue", confidence=0.9))
    assert email_payload is not None
    assert email_payload["checkout_stage"] == "otp_pending"
    assert executor.calls[-1][0] == "send_verification_code"

    otp_state = WhatsAppCheckoutState(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        channel="whatsapp",
        user_id="user-1",
        stage="checkout_auth",
        checkout_stage="otp_pending",
        pending_next_step="otp_verification",
        selected_products=["Milo"],
        customer_authenticated=False,
        otp_email="test@example.com",
        user_goal="123456",
    )
    otp_payload = resolver.resolve(otp_state, CheckoutCommand(intent="checkout_continue", confidence=0.9))
    assert otp_payload is not None
    assert otp_payload["checkout_stage"] == "shipping_method_pending"
    assert executor.calls[-1][0] == "verify_verification_code"


def test_resolver_handles_payment_to_boleta_to_order_confirmation() -> None:
    executor = FakeExecutor()
    resolver = CheckoutWorkflowResolver(executor=executor, fallback=lambda state, command: None)

    payment_state = WhatsAppCheckoutState(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        channel="whatsapp",
        user_id="user-1",
        stage="payment_selection",
        checkout_stage="payment_method_pending",
        pending_next_step="payment_selection",
        selected_products=["Milo"],
        customer_authenticated=True,
        pickup_location_label="retiro en tienda",
    )

    payment_payload = resolver.resolve(
        payment_state,
        CheckoutCommand(intent="payment_method_select", confidence=0.95, payment_method="transferencia"),
    )
    assert payment_payload is not None
    assert payment_payload["checkout_stage"] == "document_type_pending"

    document_state = WhatsAppCheckoutState(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        channel="whatsapp",
        user_id="user-1",
        stage="payment_selection",
        checkout_stage="document_type_pending",
        pending_next_step="document_type",
        payment_preference="transferencia",
        invoice_type="boleta",
        selected_products=["Milo"],
        customer_authenticated=True,
        pickup_location_label="retiro en tienda",
    )

    document_payload = resolver.resolve(
        document_state,
        CheckoutCommand(intent="document_type_select", confidence=0.95, invoice_type="boleta"),
    )
    assert document_payload is not None
    assert document_payload["checkout_stage"] == "order_summary_pending"

    confirm_state = WhatsAppCheckoutState(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        channel="whatsapp",
        user_id="user-1",
        stage="payment_selection",
        checkout_stage="order_summary_pending",
        pending_next_step="order_confirmation",
        payment_preference="transferencia",
        invoice_type="boleta",
        selected_products=["Milo"],
        customer_authenticated=True,
        pickup_location_label="retiro en tienda",
        user_goal="si confirmo",
    )

    confirm_payload = resolver.resolve(
        confirm_state,
        CheckoutCommand(intent="order_confirm", confidence=0.98),
    )
    assert confirm_payload is not None
    assert confirm_payload["checkout_stage"] == "completed"
    assert "Orden: 12345" in confirm_payload["answer"]
    assert executor.calls[-1][0] == "create_order"
