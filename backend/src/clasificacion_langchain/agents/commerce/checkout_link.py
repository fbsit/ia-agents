from __future__ import annotations

import logging
from typing import Any

from clasificacion_langchain.agents.commerce.cart_snapshot import cart_snapshot_items

logger = logging.getLogger(__name__)


def build_web_checkout_redirect(
    *,
    client: Any,
    workflow_state: dict[str, str] | None,
    session_id: str,
) -> str | None:
    """
    Arma el link publico de checkout real (shopping list del storefront propio
    del tenant, ver docs/SHOPPING_LIST_API.md en el repo de ClubHx) a partir del
    carrito actual, para el canal web. Devuelve None si no hay carrito, no hay
    storefront_url configurado para el agente, o ClubHx no pudo resolver la
    lista -el llamador decide el mensaje de fallback en ese caso, nunca un
    "/cart" relativo: el storefront real vive en otro dominio que el widget.
    """
    storefront_url = str(getattr(client, "storefront_url", "") or "").strip()
    if not storefront_url:
        logger.info("commerce_web_checkout_no_storefront_url session_id=%s", session_id)
        return None

    items = cart_snapshot_items(workflow_state)
    payload_items: list[dict[str, Any]] = []
    for item in items:
        product_id = str(item.get("product_id") or item.get("variant_id") or "").strip()
        if not product_id:
            continue
        try:
            quantity = max(1, int(item.get("quantity") or 1))
        except (TypeError, ValueError):
            quantity = 1
        payload_items.append({"product_id": product_id, "quantity": quantity})
    if not payload_items:
        return None

    try:
        result = client.create_shopping_list(
            items=payload_items,
            source="agent_web_widget",
            external_ref=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("commerce_web_checkout_shopping_list_failed session_id=%s detail=%s", session_id, exc)
        return None

    public_token = str((result or {}).get("public_token") or "").strip()
    if not public_token:
        logger.warning("commerce_web_checkout_no_token session_id=%s result=%s", session_id, result)
        return None

    return f"{storefront_url.rstrip('/')}/lista/{public_token}"


def build_web_checkout_redirect_from_requests(
    *,
    client: Any,
    cart_requests: list[dict[str, Any]],
    session_id: str,
) -> str | None:
    """
    Igual que build_web_checkout_redirect, pero a partir de pedidos de carrito
    recien parseados del mensaje ({"product_query", "quantity"}), todavia sin
    resolver contra el catalogo. La shopping list API acepta texto libre
    (campo "query") y hace su propio matching, asi que no hace falta
    resolverlos primero.
    """
    storefront_url = str(getattr(client, "storefront_url", "") or "").strip()
    if not storefront_url:
        logger.info("commerce_web_checkout_no_storefront_url session_id=%s", session_id)
        return None

    payload_items: list[dict[str, Any]] = []
    for request in cart_requests:
        query = str((request or {}).get("product_query") or "").strip()
        if not query:
            continue
        try:
            quantity = max(1, int((request or {}).get("quantity") or 1))
        except (TypeError, ValueError):
            quantity = 1
        payload_items.append({"query": query, "quantity": quantity})
    if not payload_items:
        return None

    try:
        result = client.create_shopping_list(
            items=payload_items,
            source="agent_web_widget",
            external_ref=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("commerce_web_checkout_shopping_list_failed session_id=%s detail=%s", session_id, exc)
        return None

    public_token = str((result or {}).get("public_token") or "").strip()
    if not public_token:
        logger.warning("commerce_web_checkout_no_token session_id=%s result=%s", session_id, result)
        return None

    return f"{storefront_url.rstrip('/')}/lista/{public_token}"
