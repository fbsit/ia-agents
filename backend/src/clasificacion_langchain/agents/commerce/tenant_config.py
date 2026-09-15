from __future__ import annotations

"""
Resolucion del tenant de ClubHx (whsflow) por empresa de la plataforma.

ClubHx identifica la tienda con dos datos que NO son los de la plataforma:
- `tenant_id`: UUID del tenant en whsflow (rechaza cualquier otro formato con 401).
- `X-Shop-Domain`: dominio con el que la tienda quedo conectada (p. ej. meal-prep.up.railway.app).

El codigo commerce pasa `tenant_id=company_id` en decenas de llamadas. En vez de tocar cada
call site, se envuelve el cliente con `TenantScopedClubHxClient`, que reemplaza el tenant_id
por el configurado para la empresa.

Configuracion (env):
- CLUBHX_API_BASE_URL, CLUBHX_SERVICE_TOKEN: credenciales del backend ClubHx (globales).
- CLUBHX_TENANT_MAP: JSON {company_id: {"tenant_id": "<uuid>", "shop_domain": "<dominio>"}}.
  Permite varias tiendas por despliegue.
- CLUBHX_TENANT_ID + CLUBHX_SHOP_DOMAIN (o SHOP_DOMAIN): fallback de una sola tienda.
- Si no hay mapa ni fallback y el company_id ya es un UUID, se usa tal cual (compatibilidad
  con tenants creados con el UUID de whsflow como company_id).
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from clasificacion_langchain.integrations.clubhx import ClubHxToolsClient

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class CommerceTenantConfig:
    tenant_id: str
    shop_domain: str | None = None


def _tenant_map() -> dict[str, dict[str, Any]]:
    raw = os.getenv("CLUBHX_TENANT_MAP", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("clubhx_tenant_map_invalid_json")
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_commerce_tenant(company_id: str | None) -> CommerceTenantConfig | None:
    clean_company = (company_id or "").strip()
    if not clean_company:
        return None

    entry = _tenant_map().get(clean_company)
    if isinstance(entry, dict):
        tenant_id = str(entry.get("tenant_id") or "").strip()
        if tenant_id:
            return CommerceTenantConfig(
                tenant_id=tenant_id,
                shop_domain=str(entry.get("shop_domain") or "").strip() or None,
            )

    fallback_tenant = os.getenv("CLUBHX_TENANT_ID", "").strip()
    fallback_domain = os.getenv("CLUBHX_SHOP_DOMAIN", "").strip() or os.getenv("SHOP_DOMAIN", "").strip()
    if fallback_tenant:
        return CommerceTenantConfig(tenant_id=fallback_tenant, shop_domain=fallback_domain or None)

    if _UUID_RE.match(clean_company):
        return CommerceTenantConfig(tenant_id=clean_company, shop_domain=fallback_domain or None)

    return None


class TenantScopedClubHxClient:
    """Cliente ClubHx fijado a un tenant: ignora el tenant_id que le pasen y usa el configurado."""

    def __init__(self, inner: ClubHxToolsClient, tenant_id: str) -> None:
        self._inner = inner
        self.tenant_id = tenant_id
        self.base_url = inner.base_url
        self.shop_domain = inner.shop_domain

    def execute_canonical(
        self,
        *,
        tenant_id: str,
        tool: str,
        channel: str,
        user_id: str | None,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return self._inner.execute_canonical(
            tenant_id=self.tenant_id,
            tool=tool,
            channel=channel,
            user_id=user_id,
            arguments=arguments,
        )

    def contracts(self) -> dict[str, Any]:
        return self._inner.contracts()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def build_clubhx_client_for_company(company_id: str | None) -> TenantScopedClubHxClient | None:
    base_url = os.getenv("CLUBHX_API_BASE_URL", "").strip()
    service_token = os.getenv("CLUBHX_SERVICE_TOKEN", "").strip()
    if not base_url or not service_token:
        return None
    config = resolve_commerce_tenant(company_id)
    if config is None:
        logger.info("clubhx_tenant_not_configured company_id=%s", company_id)
        return None
    timeout_seconds = int(os.getenv("CLUBHX_TOOLS_TIMEOUT_SECONDS", "12") or "12")
    inner = ClubHxToolsClient(
        base_url=base_url,
        service_token=service_token,
        shop_domain=config.shop_domain,
        timeout_seconds=timeout_seconds,
    )
    return TenantScopedClubHxClient(inner=inner, tenant_id=config.tenant_id)
