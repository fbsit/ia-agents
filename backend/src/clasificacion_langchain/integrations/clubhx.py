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
    shop_domain: str | None = None
    timeout_seconds: int = 12
    # Token separado con scope shopping_lists:write; la API de listas de
    # compra (publicables como link de checkout web) no acepta el token de
    # las tools de IA. Si no esta configurado, cae al service_token general
    # (algunos despliegues de ClubHx aceptan un INTEGRATIONS_SERVICE_TOKEN
    # global para ambos usos).
    shopping_list_service_token: str | None = None

    def _build_url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        normalized_path = path if path.startswith("/") else f"/{path}"
        if base.endswith("/api/v1") and normalized_path.startswith("/api/v1/"):
            normalized_path = normalized_path[len("/api/v1") :]
        return f"{base}{normalized_path}"

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        service_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            url=self._build_url(path),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Club-Service-Token": service_token or self.service_token,
                **(
                    {"X-Shop-Domain": self.shop_domain}
                    if self.shop_domain and self.shop_domain.strip()
                    else {}
                ),
                **(extra_headers or {}),
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

    def create_shopping_list(
        self,
        *,
        tenant_id: str,
        items: list[dict[str, Any]],
        source: str | None = None,
        external_ref: str | None = None,
        title: str | None = None,
        customer_name: str | None = None,
        customer_email: str | None = None,
        note: str | None = None,
        expires_in_hours: int | None = None,
    ) -> dict[str, Any]:
        """
        POST /api/v1/shopping-lists: arma un link publico (storefront propio del
        tenant, no Shopify) con el carrito preseleccionado, sin login ni reserva
        de stock. Ver docs/SHOPPING_LIST_API.md en el repo de ClubHx. Requiere un
        token con scope shopping_lists:write, distinto del de execute_canonical.
        """
        payload: dict[str, Any] = {"items": items}
        if source:
            payload["source"] = source
        if external_ref:
            payload["external_ref"] = external_ref
        if title:
            payload["title"] = title
        if customer_name:
            payload["customer_name"] = customer_name
        if customer_email:
            payload["customer_email"] = customer_email
        if note:
            payload["note"] = note
        if expires_in_hours:
            payload["expires_in_hours"] = expires_in_hours
        return self._post(
            "/api/v1/shopping-lists",
            payload,
            service_token=self.shopping_list_service_token or self.service_token,
            extra_headers={"X-Tenant-Id": tenant_id} if tenant_id else None,
        )

    def send_whatsapp_message(
        self,
        *,
        tenant_id: str,
        to: str,
        message: str,
    ) -> dict[str, Any]:
        return self._post(
            "/api/v1/whatsapp/send",
            {
                "tenant_id": tenant_id,
                "to": to,
                "message": message,
            },
        )
