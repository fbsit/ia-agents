from __future__ import annotations

from typing import Any, Protocol


class CommerceToolExecutor(Protocol):
    def execute(
        self,
        *,
        tenant_id: str,
        tool: str,
        channel: str,
        user_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        ...
