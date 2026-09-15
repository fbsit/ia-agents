from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.agents.commerce.commands import CheckoutCommand
from clasificacion_langchain.agents.commerce.resolver import CheckoutWorkflowResolver
from clasificacion_langchain.agents.commerce.router import CommerceWorkflowRouter
from clasificacion_langchain.agents.commerce.state import coerce_workflow_state


def test_router_maps_payload_from_graph_and_preserves_stage_metadata() -> None:
    planner_calls: list[str] = []
    resolver_calls: list[str] = []

    def planner(state):
        planner_calls.append(state.session_id)
        return CheckoutCommand(
            intent="payment_options",
            confidence=0.95,
            requested_tool="get_payment_options",
            payment_method="mercado_pago",
        )

    def resolver(state, command):
        resolver_calls.append(command.intent if command else "")
        return {
            "answer": "Perfecto, seguimos con el pago.",
            "intent_label": "payment_method_selected",
            "workflow_stage": "payment_selection",
            "checkout_stage": "document_type_pending",
            "pending_next_step": "document_type",
            "awaiting_slot": "document_type",
        }

    router = CommerceWorkflowRouter(planner=planner, resolver=resolver)

    payload = router.process_turn(
        company_id="demo",
        agent_id="agent-1",
        user_id="user-1",
        session_id="session-1",
        message="quiero pagar",
        channel="whatsapp",
        workflow_state={"stage": "payment_selection"},
    )

    assert planner_calls == ["session-1"]
    assert resolver_calls == ["payment_options"]
    assert payload is not None
    assert payload["workflow_stage"] == "payment_selection"
    assert payload["checkout_stage"] == "document_type_pending"
    assert payload["awaiting_slot"] == "document_type"


def test_router_blocks_guarded_tool_before_resolver() -> None:
    resolver_called = False

    def planner(_state):
        return CheckoutCommand(
            intent="create_payment_link",
            confidence=0.99,
            requested_tool="create_payment_link",
        )

    def resolver(_state, _command):
        nonlocal resolver_called
        resolver_called = True
        return {"answer": "esto no deberia pasar"}

    router = CommerceWorkflowRouter(planner=planner, resolver=resolver)

    payload = router.process_turn(
        company_id="demo",
        agent_id="agent-1",
        user_id="user-1",
        session_id="session-1",
        message="quiero pagar ahora",
        channel="whatsapp",
        workflow_state={},
    )

    assert resolver_called is False
    assert payload is not None
    assert payload["intent_label"] == "checkout_blocked"
    assert "checkout_stage" in payload


def test_router_resolves_lookup_payload_through_workflow_owned_resolver() -> None:
    def planner(_state):
        return CheckoutCommand(
            intent="product_lookup",
            confidence=0.95,
            requested_tool="get_product_availability",
            query="milo",
            product_queries=["milo"],
        )

    def resolver(_state, command):
        assert command is not None
        assert command.intent == "product_lookup"
        return {
            "answer": "Te paso las opciones:\n• Milo — $5490",
            "intent_label": "product_lookup",
            "workflow_stage": "product_lookup",
            "pending_next_step": "add_to_cart",
            "awaiting_slot": "quantity_or_action",
            "products": [{"id": "prod-1", "name": "Milo", "price": "5490", "stock": "200"}],
        }

    router = CommerceWorkflowRouter(planner=planner, resolver=resolver)

    payload = router.process_turn(
        company_id="demo",
        agent_id="agent-1",
        user_id="user-1",
        session_id="session-lookup",
        message="tenes milo?",
        channel="whatsapp",
        workflow_state={},
    )

    assert payload is not None
    assert payload["intent_label"] == "product_lookup"
    assert payload["pending_next_step"] == "add_to_cart"
    assert payload["products"][0]["name"] == "Milo"


def test_checkout_workflow_resolver_does_not_fall_back_for_migrated_lookup_cart_flow() -> None:
    fallback_called = False

    class FakeExecutor:
        def execute(
            self,
            *,
            tenant_id: str,
            tool: str,
            channel: str,
            user_id: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            assert tool == "get_product_availability"
            assert arguments["query"] == "Milo"
            return {
                "ok": True,
                "data": {
                    "items": [
                        {
                            "id": "prod-1",
                            "code": "milo-1",
                            "name": "Milo",
                            "price": "5490",
                            "available_units": "200",
                        }
                    ]
                },
            }

    def fallback(_state, _command):
        nonlocal fallback_called
        fallback_called = True
        return {"answer": "legacy fallback"}

    resolver = CheckoutWorkflowResolver(
        executor=FakeExecutor(),
        fallback=fallback,
        recent_products_provider=lambda _session_id: [
            {
                "id": "prod-1",
                "checkout_product_id": "milo-1",
                "variant_id": "prod-1",
                "name": "Milo",
                "price": "5490",
                "stock": "200",
            }
        ],
    )
    state = coerce_workflow_state(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-lookup-cart",
        user_id="user-1",
        channel="whatsapp",
        workflow_state={"stage": "product_lookup", "pending_next_step": "add_to_cart"},
    )
    state.user_goal = "Agregalo al carrito"
    command = CheckoutCommand(
        intent="add_to_cart",
        confidence=0.95,
        product_queries=["Milo"],
        quantity=1,
    )

    payload = resolver.resolve(state, command)

    assert fallback_called is False
    assert payload is not None
    assert payload["intent_label"] == "add_to_cart"
    assert payload["cart_action"]["item"]["name"] == "Milo"


def test_checkout_workflow_resolver_does_not_fall_back_for_resume_timeout_preflight() -> None:
    fallback_called = False
    cleared_markers = False

    class FakeExecutor:
        def execute(self, **_kwargs: Any) -> dict[str, Any]:
            raise AssertionError("resume timeout preflight should not call commerce tools")

    def fallback(_state, _command):
        nonlocal fallback_called
        fallback_called = True
        return {"answer": "legacy fallback"}

    def clear_timeout_markers() -> None:
        nonlocal cleared_markers
        cleared_markers = True

    resolver = CheckoutWorkflowResolver(
        executor=FakeExecutor(),
        fallback=fallback,
        clear_timeout_markers=clear_timeout_markers,
        is_affirmative_message=lambda message: message.strip().lower() == "si",
        is_greeting_message=lambda _message: False,
    )
    state = coerce_workflow_state(
        company_id="demo",
        agent_id="agent-1",
        session_id="session-timeout-resume",
        user_id="user-1",
        channel="whatsapp",
        workflow_state={
            "stage": "payment_selection",
            "pending_next_step": "payment_selection",
            "workflow_timeout_confirmation": "true",
        },
    )
    state.user_goal = "si"

    payload = resolver.resolve(state, None)

    assert fallback_called is False
    assert cleared_markers is True
    assert payload is not None
    assert payload["intent_label"] == "payment_options"
