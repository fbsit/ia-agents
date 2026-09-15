from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.agents.commerce.persistence import CheckoutSessionSummaryAdapter
from clasificacion_langchain.chat.session_store import SessionSummary


def test_checkout_summary_adapter_roundtrip_uses_existing_session_summary_fields() -> None:
    summary = SessionSummary(
        funnel_stage="payment_selection",
        checkout_stage="document_type_pending",
        pending_next_step="document_type",
        awaiting_slot="document_type",
        selected_products="Milo, Avena",
        focused_product="Milo",
        payment_preference="Transferencia bancaria",
        otp_email="cliente@test.com",
    )

    state = CheckoutSessionSummaryAdapter.from_summary(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        channel="whatsapp",
        summary=summary,
    )

    assert state.stage == "payment_selection"
    assert state.checkout_stage == "document_type_pending"
    assert state.selected_products == ["Milo", "Avena"]
    assert state.payment_preference == "Transferencia bancaria"
    assert state.otp_email == "cliente@test.com"

    projected = CheckoutSessionSummaryAdapter.to_summary(summary, state)

    assert projected.funnel_stage == "payment_selection"
    assert projected.checkout_stage == "document_type_pending"
    assert projected.pending_next_step == "document_type"
    assert projected.awaiting_slot == "document_type"


def test_checkout_summary_adapter_tolerates_missing_optional_fields() -> None:
    summary = SessionSummary(funnel_stage="shipping_selection")

    state = CheckoutSessionSummaryAdapter.from_summary(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        channel="whatsapp",
        summary=summary,
    )

    assert state.delivery_address == ""
    assert state.invoice_address == ""
    assert state.pickup_location_label == ""
    assert state.selected_products == []
