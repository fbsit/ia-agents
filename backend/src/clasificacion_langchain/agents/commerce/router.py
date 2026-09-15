from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from clasificacion_langchain.agents.commerce.commands import CheckoutCommand
from clasificacion_langchain.agents.commerce.graph import build_checkout_workflow_graph
from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState, coerce_workflow_state


PlannerFn = Callable[[WhatsAppCheckoutState], CheckoutCommand | None]
ResolverFn = Callable[[WhatsAppCheckoutState, CheckoutCommand | None], dict[str, Any] | None]


@dataclass
class CommerceWorkflowRouter:
    planner: PlannerFn
    resolver: ResolverFn
    commerce_client: Any = None

    def __post_init__(self) -> None:
        # Router is request-scoped because resolver dependencies such as tool clients,
        # feature flags, and response context still come from the API boundary.
        self._graph = build_checkout_workflow_graph(
            planner=self.planner,
            resolver=self.resolver,
            commerce_client=self.commerce_client,
        )

    def process_turn(
        self,
        *,
        company_id: str,
        agent_id: str | None,
        user_id: str,
        session_id: str,
        message: str,
        channel: str,
        workflow_state: dict[str, str] | None,
    ) -> dict[str, Any] | None:
        checkout_state = coerce_workflow_state(
            company_id=company_id,
            agent_id=agent_id or "",
            session_id=session_id,
            channel=channel,
            workflow_state=workflow_state,
            user_id=user_id,
        )
        checkout_state.user_goal = message.strip()
        graph_state = self._graph.invoke({"checkout_state": checkout_state})
        payload = graph_state.get("payload") if isinstance(graph_state, dict) else None
        return payload if isinstance(payload, dict) else None
