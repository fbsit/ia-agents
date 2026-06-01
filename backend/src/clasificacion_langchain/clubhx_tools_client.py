from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


@dataclass
class ClubHxToolsClient:
    base_url: str
    service_token: str
    timeout_seconds: int = 12

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            url=f"{self.base_url.rstrip('/')}{path}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Club-Service-Token": self.service_token,
            },
            data=body,
        )
        try:
            with urllib_request.urlopen(req, timeout=max(3, self.timeout_seconds)) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            raise RuntimeError(f"clubhx_http_error:{exc.code}:{detail}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"clubhx_unreachable:{exc.reason}") from exc

    def contracts(self) -> dict[str, Any]:
        return self._post("/api/v1/ai/tools/contracts", {})

    def execute_canonical(
        self,
        *,
        tenant_id: str,
        tool: str,
        channel: str,
        user_id: str | None,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "tool": tool,
            "channel": channel,
            "arguments": arguments,
        }
        if user_id:
            payload["user_id"] = user_id
        return self._post("/api/v1/ai/tools/execute-canonical", payload)
