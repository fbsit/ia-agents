from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from clasificacion_langchain.agents.commerce.cart_snapshot import cart_snapshot_items

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _cart_item_to_shopping_list_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """
    El carrito persistido guarda en `product_id` el `code` de ClubHx cuando
    existe (para el resto del flujo de checkout, que acepta code o id), no
    siempre un UUID; el UUID real, cuando esta disponible, es `variant_id`.
    La shopping list API exige UUID en `product_id` (400 si no lo es), pero
    tiene un campo `code` aparte para identificadores no-UUID: se prueban en
    orden en vez de asumir que uno u otro trae siempre el UUID.
    """
    try:
        quantity = max(1, int(item.get("quantity") or 1))
    except (TypeError, ValueError):
        quantity = 1
    variant_id = str(item.get("variant_id") or "").strip()
    product_id = str(item.get("product_id") or "").strip()
    if variant_id and _UUID_RE.match(variant_id):
        return {"product_id": variant_id, "quantity": quantity}
    if product_id and _UUID_RE.match(product_id):
        return {"product_id": product_id, "quantity": quantity}
    code = product_id or variant_id
    if code:
        return {"code": code, "quantity": quantity}
    name = str(item.get("name") or "").strip()
    if name:
        return {"query": name, "quantity": quantity}
    return None


@dataclass(slots=True, frozen=True)
class WebCheckoutLink:
    url: str
    unmatched_count: int = 0
    ambiguous_count: int = 0


def _create_list_link(
    *,
    client: Any,
    payload_items: list[dict[str, Any]],
    session_id: str,
) -> WebCheckoutLink | None:
    storefront_url = str(getattr(client, "storefront_url", "") or "").strip()
    if not storefront_url or not payload_items:
        if not storefront_url:
            logger.info("commerce_web_checkout_no_storefront_url session_id=%s", session_id)
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

    totals = (result or {}).get("totals") if isinstance((result or {}).get("totals"), dict) else {}
    try:
        unmatched_count = int(totals.get("unmatched_count") or 0)
    except (TypeError, ValueError):
        unmatched_count = 0
    try:
        ambiguous_count = int(totals.get("ambiguous_count") or 0)
    except (TypeError, ValueError):
        ambiguous_count = 0

    return WebCheckoutLink(
        url=f"{storefront_url.rstrip('/')}/lista/{public_token}",
        unmatched_count=unmatched_count,
        ambiguous_count=ambiguous_count,
    )


def describe_web_checkout_answer(link: WebCheckoutLink) -> str:
    """
    Mensaje para acompanar el redirect. ClubHx resuelve el carrito contra su
    catalogo (~53 productos hoy): lo que no encuentra queda "not_found" y no
    entra al link. Mejor avisarlo en el chat que dejar que el cliente lo
    descubra recien al abrir la pagina.
    """
    if link.unmatched_count > 0 and link.ambiguous_count > 0:
        return (
            "Te dejo el carrito listo, pero ojo: algunos productos no los encontre y otros quedaron "
            "para que confirmes cual es en la pagina. Entra, revisa, inicia sesion y termina la compra."
        )
    if link.unmatched_count > 0:
        return (
            "Te dejo el carrito listo, pero algunos productos no los encontre en el catalogo asi que no "
            "quedaron incluidos. Entra, revisa que este todo, inicia sesion y termina la compra."
        )
    if link.ambiguous_count > 0:
        return (
            "Te dejo el carrito listo, alguno quedo para que confirmes cual es exactamente en la pagina. "
            "Entra, revisa, inicia sesion y termina la compra."
        )
    return "Te dejo el carrito listo para que lo revises, inicies sesion y termines la compra."


def build_web_checkout_redirect(
    *,
    client: Any,
    workflow_state: dict[str, str] | None,
    session_id: str,
) -> WebCheckoutLink | None:
    """
    Arma el link publico de checkout real (shopping list del storefront propio
    del tenant, ver docs/SHOPPING_LIST_API.md en el repo de ClubHx) a partir del
    carrito persistido (cart_snapshot), para el canal web. Devuelve None si no
    hay carrito, no hay storefront_url configurado para el agente, o ClubHx no
    pudo resolver la lista -el llamador decide el mensaje de fallback en ese
    caso, nunca un "/cart" relativo: el storefront real vive en otro dominio
    que el widget.
    """
    payload_items: list[dict[str, Any]] = []
    for item in cart_snapshot_items(workflow_state):
        mapped = _cart_item_to_shopping_list_item(item)
        if mapped is not None:
            payload_items.append(mapped)
    return _create_list_link(client=client, payload_items=payload_items, session_id=session_id)


def build_web_checkout_redirect_from_requests(
    *,
    client: Any,
    cart_requests: list[dict[str, Any]],
    session_id: str,
) -> WebCheckoutLink | None:
    """
    Igual que build_web_checkout_redirect, pero a partir de pedidos de carrito
    recien parseados del mensaje ({"product_query", "quantity"}), todavia sin
    resolver contra el catalogo. La shopping list API acepta texto libre
    (campo "query") y hace su propio matching, asi que no hace falta
    resolverlos primero.
    """
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
    return _create_list_link(client=client, payload_items=payload_items, session_id=session_id)
