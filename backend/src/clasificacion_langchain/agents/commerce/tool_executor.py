from __future__ import annotations

from typing import Any

from clasificacion_langchain.agents.commerce.tool_ports import CommerceToolExecutor


class CanonicalCommerceToolExecutor(CommerceToolExecutor):
    def __init__(self, client: Any) -> None:
        self.client = client

    def execute(
        self,
        *,
        tenant_id: str,
        tool: str,
        channel: str,
        user_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("commerce tools client unavailable")
        result = self.client.execute_canonical(
            tenant_id=tenant_id,
            tool=tool,
            channel=channel,
            user_id=user_id,
            arguments=arguments,
        )
        return result if isinstance(result, dict) else {"ok": False, "data": {}, "raw": result}

    def lookup_products(
        self,
        *,
        tenant_id: str,
        channel: str,
        user_id: str,
        session_id: str,
        queries: list[str],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return [
            self.execute(
                tenant_id=tenant_id,
                tool="get_product_availability",
                channel=channel,
                user_id=user_id,
                arguments={"query": query, "limit": limit, "session_id": session_id},
            )
            for query in queries
            if str(query or "").strip()
        ]
