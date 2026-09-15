from __future__ import annotations

from typing import Any, Callable, TypedDict

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from clasificacion_langchain.agents.commerce.commands import CheckoutCommand
from clasificacion_langchain.agents.commerce.guards import evaluate_tool_guard
from clasificacion_langchain.agents.commerce.response_mapper import map_checkout_response_payload
from clasificacion_langchain.agents.commerce.slots import align_command_to_stage, merge_command_into_state
from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState, apply_payload_state


class CheckoutWorkflowGraphState(TypedDict, total=False):
    checkout_state: WhatsAppCheckoutState
    command: CheckoutCommand | None
    tool_guard_allowed: bool
    tool_guard_reason: str
    tool_guard_clarification: str
    payload: dict[str, Any] | None


def build_checkout_workflow_graph(
    *,
    planner: Callable[[WhatsAppCheckoutState], CheckoutCommand | None],
    resolver: Callable[[WhatsAppCheckoutState, CheckoutCommand | None], dict[str, Any] | None],
):
    # Graph authority stays intentionally small in phase one:
    # plan -> guard -> resolve -> compatibility map.
    # Deeper legacy commerce behavior is still delegated by the resolver
    # until the strangler migration can delete the old helper branches safely.
    def plan_node(state: CheckoutWorkflowGraphState) -> CheckoutWorkflowGraphState:
        checkout_state = state["checkout_state"]
        command = planner(checkout_state)
        command = align_command_to_stage(checkout_state, command)
        next_checkout_state = merge_command_into_state(checkout_state, command)
        return {
            "command": command,
            "checkout_state": next_checkout_state,
        }

    def guard_node(state: CheckoutWorkflowGraphState) -> CheckoutWorkflowGraphState:
        command = state.get("command")
        tool_name = command.requested_tool if command is not None else ""
        decision = evaluate_tool_guard(state["checkout_state"], tool_name)
        return {
            "tool_guard_allowed": decision.allowed,
            "tool_guard_reason": decision.reason,
            "tool_guard_clarification": decision.clarification,
        }

    def execute_or_block_node(state: CheckoutWorkflowGraphState) -> CheckoutWorkflowGraphState:
        checkout_state = state["checkout_state"]
        if not state.get("tool_guard_allowed", True):
            payload = {
                "answer": state.get("tool_guard_clarification") or "No puedo avanzar con ese paso todavia.",
                "intent_label": "checkout_blocked",
                "workflow_stage": checkout_state.stage,
                "checkout_stage": checkout_state.checkout_stage,
                "pending_next_step": checkout_state.pending_next_step,
                "awaiting_slot": checkout_state.awaiting_slot,
            }
            if state.get("tool_guard_reason") == "auth_required":
                # Dejar el checkout esperando el correo: el siguiente mensaje con un email dispara el OTP.
                payload.update(
                    {
                        "answer": (
                            "Antes de continuar con el pago necesito validar tu acceso. "
                            "Escribime tu correo y te envio un codigo de verificacion."
                        ),
                        "intent_label": "checkout_auth_needed",
                        "workflow_stage": "checkout_ready",
                        "checkout_stage": "auth_pending",
                        "pending_next_step": "auth_confirmation",
                        "awaiting_slot": "",
                    }
                )
            return {"payload": payload}
        payload = resolver(checkout_state, state.get("command"))
        return {
            "payload": payload,
            "checkout_state": apply_payload_state(checkout_state, payload),
        }

    def map_node(state: CheckoutWorkflowGraphState) -> CheckoutWorkflowGraphState:
        return {
            "payload": map_checkout_response_payload(
                state.get("payload"),
                state["checkout_state"],
            )
        }

    graph = StateGraph(CheckoutWorkflowGraphState)
    graph.add_node("plan", RunnableLambda(plan_node))
    graph.add_node("guard", RunnableLambda(guard_node))
    graph.add_node("execute_or_block", RunnableLambda(execute_or_block_node))
    graph.add_node("map", RunnableLambda(map_node))
    graph.set_entry_point("plan")
    graph.add_edge("plan", "guard")
    graph.add_edge("guard", "execute_or_block")
    graph.add_edge("execute_or_block", "map")
    graph.add_edge("map", END)
    return graph.compile()
