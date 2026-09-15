from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.agents.commerce.commands import CheckoutCommand
from clasificacion_langchain.agents.commerce.slots import align_command_to_stage, merge_command_into_state, resolve_missing_slots
from clasificacion_langchain.agents.commerce.state import coerce_workflow_state


def test_merge_command_into_state_sets_first_class_slots() -> None:
    state = coerce_workflow_state(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        channel="whatsapp",
        workflow_state={"awaiting_slot": "payment_method"},
    )
    command = CheckoutCommand(
        intent="payment_options",
        confidence=0.94,
        product_queries=["Milo"],
        payment_method="mercado_pago",
        customer_goal="cerrar compra",
    )

    merged = merge_command_into_state(state, command)

    assert merged.selected_products == ["Milo"]
    assert merged.focused_product == "Milo"
    assert merged.payment_preference == "mercado_pago"
    assert merged.user_goal == "cerrar compra"


def test_resolve_missing_slots_ignores_optional_empty_values() -> None:
    state = coerce_workflow_state(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        channel="whatsapp",
        workflow_state={
            "awaiting_slot": "shipping_method",
            "invoice_address": "",
            "pickup_location_label": "",
        },
    )

    result = resolve_missing_slots(state)

    assert result.missing == ["shipping_method"]


def test_align_command_to_stage_normalizes_quantity_only_followup_for_cart_step() -> None:
    state = coerce_workflow_state(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        channel="whatsapp",
        workflow_state={
            "stage": "product_lookup",
            "pending_next_step": "add_to_cart",
            "awaiting_slot": "quantity_or_action",
            "focused_product": "Milo",
        },
    )
    command = CheckoutCommand(
        intent="none",
        confidence=0.2,
        query="2",
        quantity=2,
        quantity_only_followup=True,
    )

    aligned = align_command_to_stage(state, command)

    assert aligned is not None
    assert aligned.intent == "add_to_cart"
