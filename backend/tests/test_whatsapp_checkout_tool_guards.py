from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.agents.commerce.guards import evaluate_tool_guard
from clasificacion_langchain.agents.commerce.state import coerce_workflow_state


def test_create_payment_link_requires_products_and_auth() -> None:
    state = coerce_workflow_state(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        channel="whatsapp",
        workflow_state={},
    )

    blocked = evaluate_tool_guard(state, "create_payment_link")

    assert blocked.allowed is False
    assert blocked.reason == "missing_products"


def test_create_order_draft_allows_authenticated_checkout() -> None:
    state = coerce_workflow_state(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        channel="whatsapp",
        workflow_state={
            "selected_products": "Milo",
            "customer_authenticated": "true",
        },
    )

    allowed = evaluate_tool_guard(state, "create_order_draft")

    assert allowed.allowed is True
