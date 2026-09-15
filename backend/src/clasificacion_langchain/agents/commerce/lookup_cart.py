from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from clasificacion_langchain.agents.commerce.cart_snapshot import (
    build_cart_status_answer_from_snapshot,
    cart_snapshot_items,
    enrich_cart_snapshot_prices,
)
from clasificacion_langchain.agents.commerce.commands import CheckoutCommand
from clasificacion_langchain.agents.commerce.extractors import (
    extract_widget_remove_from_cart,
    extract_widget_set_cart_quantity,
    is_remove_from_cart_message,
    is_set_cart_quantity_message,
)
from clasificacion_langchain.agents.commerce.recent_products import (
    has_explicit_add_to_cart_intent,
    is_implicit_add_to_cart_message,
    is_quantity_only_followup,
    match_recent_product_from_message,
    normalize_text,
    parse_quantity,
)
from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState
from clasificacion_langchain.agents.commerce.tool_ports import CommerceToolExecutor


RecentProductsProvider = Callable[[str], list[dict[str, Any]]]


@dataclass
class LookupCartResolution:
    payload: dict[str, Any] | None
    handled: bool


def _is_clear_cart_message(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return any(
        phrase in normalized
        for phrase in [
            "reseteame el carrito",
            "resetea el carrito",
            "limpia el carrito",
            "vacia el carrito",
            "vacia carrito",
            "vaciame el carrito",
            "borra el carrito",
            "deja el carrito vacio",
            "deja el carrito vacia",
        ]
    )


def _is_cart_status_message(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return "carrito" in normalized and any(token in normalized for token in ["como va", "resumen", "estado", "mi carrito", "carrito actual", "va el carrito"])


def _looks_like_product_question(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    if message.strip().endswith("?") or message.strip().startswith("¿"):
        return True
    return bool(re.match(r"^(tienen|tenes|tiene|hay|venden|vende|manejan|trabajan|cuanto|cuánto|que|qué|cual|cuál)", normalized))


def _singularize_query(query: str) -> str:
    """'bandejas de huevos' -> 'bandeja de huevo': el buscador de ClubHx no siempre resuelve plurales."""
    words = []
    for word in query.split():
        lowered = word.lower()
        if len(lowered) > 3 and lowered.endswith("s") and not lowered.endswith("ss"):
            words.append(word[:-1])
        else:
            words.append(word)
    return " ".join(words)


_ADD_VERB_TOKENS = re.compile(r"^(?:agreg\w*|pon\w*|met\w*|sum\w*|anad\w*|añad\w*|llev\w*|dale|si|ok|oka|va|bueno|eso|ese|esa|este|esta|mismo|misma)$")


_REMOVE_VERBS = re.compile(r"\b(?:quit\w*|sac\w+le|sacame|sacar|saca|remuev\w*|remov\w*|elimin\w*|borr\w*|descart\w*)\b")


def _names_a_product(product_query: str) -> bool:
    """'agregalo' o 'ponelo' no nombran un producto; 'bandeja de huevo' si."""
    tokens = [token for token in normalize_text(product_query).split() if len(token) > 1]
    return any(not _ADD_VERB_TOKENS.match(token) for token in tokens)


def _match_cart_item(items: list[dict[str, Any]], product_query: str) -> dict[str, Any] | None:
    """Elige el item del carrito que mejor coincide con lo que nombro el cliente."""
    query_tokens = {token for token in normalize_text(_singularize_query(product_query)).split() if len(token) > 2}
    if not query_tokens:
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for item in items:
        name_tokens = {token for token in normalize_text(_singularize_query(str(item.get("name") or ""))).split() if len(token) > 2}
        overlap = len(query_tokens & name_tokens)
        if overlap and (best is None or overlap > best[0]):
            best = (overlap, item)
    return best[1] if best else None


def _extract_widget_cart_requests(message: str) -> list[dict[str, Any]]:
    normalized = normalize_text(message)
    if not normalized or not has_explicit_add_to_cart_intent(message):
        return []
    segments = [part.strip() for part in re.split(r"\s+(?:y|e|ademas|tambien)\s+", normalized) if part.strip()]
    requests: list[dict[str, Any]] = []
    for segment in segments:
        cleaned = re.sub(
            r"\b(?:agrega|agregame|agregar|suma|sumame|sumar|pon|poneme|poner|mete|meteme|anade|llevo|quiero|porfa|por favor|al|carrito|el|la|los|las)\b",
            " ",
            segment,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            continue
        quantity = parse_quantity(segment)
        product_query = re.sub(r"^\d+\s+", "", cleaned).strip()
        product_query = re.sub(r"^(un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+", "", product_query).strip()
        if product_query:
            requests.append({"quantity": quantity, "product_query": product_query})
    return requests


def _selected_product_requests_from_workflow_state(workflow_state: dict[str, str] | None) -> list[dict[str, Any]]:
    raw = str((workflow_state or {}).get("selected_products") or "").strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    candidates: list[str] = []
    for chunk in re.split(r"[,\n;•]+", raw):
        cleaned = chunk.strip().strip("'\"")
        if cleaned:
            candidates.append(cleaned)
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_text(candidate)
        if key and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return [{"product_query": name, "quantity": 1} for name in unique[:6]]


def _normalize_catalog_product(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or "").strip(),
        "checkout_product_id": str(item.get("code") or item.get("id") or "").strip(),
        "variant_id": str(item.get("id") or "").strip(),
        "name": str(item.get("name") or "Producto").strip() or "Producto",
        "price": str(item.get("price") or "N/D").strip(),
        "stock": str(item.get("available_units") or item.get("stock") or "0").strip(),
        "image_url": str(item.get("image_url") or "").strip() or None,
    }


def _build_multi_cart_tool_payload(canonical_results: list[dict[str, Any]], cart_requests: list[dict[str, Any]]) -> dict[str, Any] | None:
    cart_actions: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    seen_products: set[str] = set()
    for cart_request, result in zip(cart_requests, canonical_results):
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        safe_items = [item for item in items if isinstance(item, dict)]
        if not safe_items:
            continue
        first = safe_items[0]
        product_id = str(first.get("id") or "").strip()
        if not product_id:
            continue
        checkout_product_id = str(first.get("code") or first.get("id") or "").strip()
        variant_id = str(first.get("id") or "").strip()
        name = str(first.get("name") or "Producto").strip() or "Producto"
        cart_action_item = {
            "product_id": checkout_product_id or product_id,
            "checkout_product_id": checkout_product_id or product_id,
            "variant_id": variant_id or product_id,
            "quantity": int(cart_request.get("quantity") or 1),
            "name": name,
        }
        cart_actions.append({"type": "add_to_cart", "item": cart_action_item})
        for item in safe_items[:3]:
            current_id = str(item.get("id") or "").strip()
            if not current_id or current_id in seen_products:
                continue
            seen_products.add(current_id)
            products.append(_normalize_catalog_product(item))
    if not cart_actions:
        return None
    summary = " y ".join(
        f"{action['item']['quantity']} {action['item']['name']}" for action in cart_actions if isinstance(action, dict)
    )
    return {
        "answer": f'Listo, agregue {summary} al carrito. Si queres, seguimos con checkout cuando me digas "quiero pagar".',
        "intent_label": "add_to_cart",
        "cart_action": cart_actions[0],
        "cart_actions": cart_actions,
        "products": products[:6],
        "focused_product": str(((cart_actions[0].get("item") or {}).get("name") or "")).strip(),
        "workflow_stage": "cart_building",
        "pending_next_step": "shipping_selection",
        "awaiting_slot": "shipping_method",
    }


def _build_multi_product_lookup_payload(canonical_results: list[dict[str, Any]], queries: list[str], user_message: str) -> dict[str, Any] | None:
    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query, result in zip(queries, canonical_results):
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        safe_items = [item for item in items if isinstance(item, dict)]
        for item in safe_items[:3]:
            product_id = str(item.get("id") or "").strip()
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            normalized_product = _normalize_catalog_product(item)
            normalized_product["query"] = query
            products.append(normalized_product)
    if not products:
        return None
    normalized_message = normalize_text(user_message)
    answer = "Si, encontre estas opciones:" if any(token in normalized_message for token in ["stock", "disponible", "precio", "cuesta", "tienen", "tiene", "hay"]) else "Te paso las opciones:"
    formatted = "\n".join(f"• {p['name']} — ${p['price']}" for p in products[:5] if p.get("name"))
    if formatted:
        answer = f"{answer}\n{formatted}"
    return {
        "answer": answer,
        "products": products[:6],
        "focused_product": products[0]["name"] if products else "",
        "workflow_stage": "product_lookup",
        "pending_next_step": "add_to_cart",
        "awaiting_slot": "quantity_or_action",
    }


@dataclass
class LookupCartResolver:
    executor: CommerceToolExecutor
    recent_products_provider: RecentProductsProvider

    def resolve(self, state: WhatsAppCheckoutState, command: CheckoutCommand | None) -> LookupCartResolution:
        # Migration boundary: discovery/cart behaviors resolve here so `chat_api.py`
        # stops being the primary owner of WhatsApp commerce lookup/cart semantics.
        payload = self._resolve_remove_or_set_cart(state)
        if payload is not None:
            return LookupCartResolution(payload=payload, handled=True)
        payload = self._resolve_recent_or_focused_followup(state, command)
        if payload is not None:
            return LookupCartResolution(payload=payload, handled=True)
        payload = self._resolve_direct_cart(state, command)
        if payload is not None:
            return LookupCartResolution(payload=payload, handled=True)
        payload = self._resolve_clear_cart(state)
        if payload is not None:
            return LookupCartResolution(payload=payload, handled=True)
        payload = self._resolve_cart_status(state, command)
        if payload is not None:
            return LookupCartResolution(payload=payload, handled=True)
        payload = self._resolve_product_lookup(state, command)
        if payload is not None:
            return LookupCartResolution(payload=payload, handled=True)
        return LookupCartResolution(payload=None, handled=False)

    def _lookup(self, state: WhatsAppCheckoutState, query: str, limit: int = 5) -> dict[str, Any]:
        """get_product_availability con reintento en singular si el plural no encuentra nada."""
        def _run(text: str) -> dict[str, Any]:
            return self.executor.execute(
                tenant_id=state.company_id,
                tool="get_product_availability",
                channel=state.channel,
                user_id=state.user_id,
                arguments={"query": text, "limit": limit, "session_id": state.session_id},
            )

        result = _run(query)
        data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else {}
        if isinstance(data.get("items"), list) and data.get("items"):
            return result
        singular = _singularize_query(query)
        if singular != query:
            retry = _run(singular)
            retry_data = retry.get("data") if isinstance(retry, dict) and isinstance(retry.get("data"), dict) else {}
            if isinstance(retry_data.get("items"), list) and retry_data.get("items"):
                return retry
        return result

    def _resolve_remove_or_set_cart(self, state: WhatsAppCheckoutState) -> dict[str, Any] | None:
        """'quitame el milo', 'sacale una bandeja', 'deja solo 1 omo': operan sobre el carrito local."""
        message = state.user_goal
        # "sacale una bandeja", "quitale el milo", "elimina el omo": conjugaciones que el
        # detector de frases fijas no cubre.
        remove = is_remove_from_cart_message(message) or bool(
            _REMOVE_VERBS.search(normalize_text(message))
        )
        set_quantity = not remove and is_set_cart_quantity_message(message)
        if not remove and not set_quantity:
            return None
        request = extract_widget_remove_from_cart(message) if remove else extract_widget_set_cart_quantity(message)
        product_query = str((request or {}).get("product_query") or "").strip()
        items = cart_snapshot_items(state.to_workflow_state_dict())
        if not items:
            return {
                "answer": "Tu carrito esta vacio, no hay nada que quitar. Decime que producto queres llevar y te lo agrego.",
                "intent_label": "cart_empty",
                "workflow_stage": "browsing",
            }
        target = _match_cart_item(items, product_query) if product_query else (items[0] if len(items) == 1 else None)
        if target is None:
            names = ", ".join(str(item.get("name") or "Producto") for item in items[:6])
            return {
                "answer": f"No encontre ese producto en tu carrito. Ahora tenes: {names}. Decime cual queres cambiar.",
                "intent_label": "cart_item_not_found",
                "workflow_stage": "cart_building",
            }
        try:
            current_quantity = max(1, int(target.get("quantity") or 1))
        except (TypeError, ValueError):
            current_quantity = 1
        product_id = str(target.get("product_id") or "").strip()
        name = str(target.get("name") or "Producto").strip() or "Producto"
        explicit_quantity = bool(re.search(r"\b\d+\b|\b(un|una|uno|dos|tres|cuatro|cinco)\b", normalize_text(message)))
        requested = max(1, int((request or {}).get("quantity") or 1))
        if remove:
            quantity = requested if explicit_quantity else current_quantity
            quantity = min(quantity, current_quantity)
            remaining = current_quantity - quantity
            action = {"type": "remove_from_cart", "item": {"product_id": product_id, "name": name, "quantity": quantity}}
            answer = (
                f"Listo, quite {name} del carrito."
                if remaining <= 0
                else f"Listo, quite {quantity} {name}. Te quedan {remaining} en el carrito."
            )
            intent = "remove_from_cart"
        else:
            quantity = requested
            action = {"type": "set_cart_quantity", "item": {"product_id": product_id, "name": name, "quantity": quantity}}
            answer = f"Listo, deje {quantity} {name} en el carrito."
            intent = "set_cart_quantity"
        others = [item for item in items if str(item.get("product_id") or "") != product_id]
        if remove and current_quantity - quantity <= 0 and not others:
            answer += " Tu carrito quedo vacio."
        return {
            "answer": answer,
            "intent_label": intent,
            "workflow_stage": "cart_building" if (others or (remove and current_quantity - quantity > 0) or not remove) else "browsing",
            "cart_action": action,
            "cart_actions": [action],
        }

    def _resolve_product_lookup(self, state: WhatsAppCheckoutState, command: CheckoutCommand | None) -> dict[str, Any] | None:
        if command is None:
            return None
        if command.intent != "product_lookup" and command.requested_tool != "get_product_availability":
            return None
        queries = [query for query in command.product_queries if query]
        if not queries and command.query:
            queries = [command.query]
        if not queries:
            return None
        canonical_results = [self._lookup(state, query) for query in queries]
        return _build_multi_product_lookup_payload(canonical_results, queries, state.user_goal)

    def _resolve_recent_or_focused_followup(self, state: WhatsAppCheckoutState, command: CheckoutCommand | None) -> dict[str, Any] | None:
        workflow_state = state.to_workflow_state_dict()
        pending_next_step = str(workflow_state.get("pending_next_step") or "").strip().lower()
        workflow_stage = str(workflow_state.get("stage") or "").strip().lower()
        awaiting_slot = str(workflow_state.get("awaiting_slot") or "").strip().lower()
        if pending_next_step != "add_to_cart" and workflow_stage != "product_lookup":
            return None
        # Una pregunta ("Tienen Omo?", "Hay cafe?") es una consulta, no una orden de agregar:
        # sigue el camino de busqueda aunque el estado anterior haya quedado en product_lookup.
        if _looks_like_product_question(state.user_goal) and not (
            has_explicit_add_to_cart_intent(state.user_goal) or is_quantity_only_followup(state.user_goal)
        ):
            return None
        # "quiero 1 omo y 1 nescafe": varios productos en un mensaje -> resolver todos contra el catalogo.
        multi_requests: list[dict[str, Any]] = []
        if command is not None and command.product_queries and len(command.product_queries) > 1:
            multi_requests = [
                {"quantity": command.quantity or 1, "product_query": str(query).strip()}
                for query in command.product_queries
                if str(query).strip()
            ]
        if len(multi_requests) < 2:
            # "agregame 2 bandejas de huevo" nombra el producto: se busca ese, aunque el ultimo
            # mostrado haya sido otro (antes se agregaba el producto reciente equivocado).
            extracted = [
                request
                for request in _extract_widget_cart_requests(state.user_goal)
                if _names_a_product(str(request.get("product_query") or ""))
            ]
            if extracted:
                multi_requests = extracted
        if len(multi_requests) >= 1:
            canonical_results = [
                self._lookup(state, str(cart_request.get("product_query") or "").strip())
                for cart_request in multi_requests
            ]
            payload = _build_multi_cart_tool_payload(canonical_results, multi_requests)
            if isinstance(payload, dict):
                payload["awaiting_slot"] = "shipping_method"
                return payload
        recent_products = self.recent_products_provider(state.session_id)
        selected_product = None
        recent_query = ""
        if command is not None and command.product_queries:
            recent_query = str(command.product_queries[0] or "").strip()
        if is_implicit_add_to_cart_message(state.user_goal):
            selected_product = recent_products[0] if recent_products else None
        elif recent_query:
            selected_product = match_recent_product_from_message(recent_query, recent_products)
        else:
            selected_product = match_recent_product_from_message(state.user_goal, recent_products)
        if isinstance(selected_product, dict):
            product_id = str(selected_product.get("id") or "").strip()
            if not product_id:
                return None
            checkout_product_id = str(selected_product.get("checkout_product_id") or product_id).strip()
            variant_id = str(selected_product.get("variant_id") or product_id).strip()
            name = str(selected_product.get("name") or "Producto").strip() or "Producto"
            quantity = command.quantity if command is not None and command.quantity else parse_quantity(state.user_goal)
            cart_action = {
                "type": "add_to_cart",
                "item": {
                    "product_id": checkout_product_id or product_id,
                    "checkout_product_id": checkout_product_id or product_id,
                    "variant_id": variant_id or product_id,
                    "quantity": quantity,
                    "name": name,
                },
            }
            return {
                "answer": f'Listo, agregue {quantity} {name} al carrito. Si queres, seguimos con checkout cuando me digas "quiero pagar".',
                "intent_label": "add_to_cart",
                "workflow_stage": "cart_building",
                "pending_next_step": "shipping_selection",
                "cart_action": cart_action,
                "cart_actions": [cart_action],
                "products": [selected_product],
            }
        implicit_add = is_implicit_add_to_cart_message(state.user_goal)
        if awaiting_slot != "quantity_or_action" and not is_quantity_only_followup(state.user_goal) and not implicit_add:
            return None
        workflow_requests = _selected_product_requests_from_workflow_state(workflow_state)
        if not workflow_requests:
            return None
        quantity = command.quantity if command is not None and command.quantity else parse_quantity(state.user_goal)
        cart_request = dict(workflow_requests[0])
        cart_request["quantity"] = quantity
        canonical_result = self.executor.execute(
            tenant_id=state.company_id,
            tool="get_product_availability",
            channel=state.channel,
            user_id=state.user_id,
            arguments={
                "query": str(cart_request.get("product_query") or "").strip(),
                "limit": 5,
                "session_id": state.session_id,
            },
        )
        payload = _build_multi_cart_tool_payload([canonical_result], [cart_request])
        if isinstance(payload, dict):
            payload["focused_product"] = str(workflow_state.get("focused_product") or cart_request.get("product_query") or "").strip()
            payload["awaiting_slot"] = "shipping_method"
        return payload

    def _resolve_direct_cart(self, state: WhatsAppCheckoutState, command: CheckoutCommand | None) -> dict[str, Any] | None:
        workflow_state = state.to_workflow_state_dict()
        if str(workflow_state.get("pending_next_step") or "").strip().lower() == "add_to_cart" or str(workflow_state.get("stage") or "").strip().lower() == "product_lookup":
            return None
        cart_requests: list[dict[str, Any]] = []
        if command is not None and command.intent == "add_to_cart" and command.product_queries:
            cart_requests = [
                {"quantity": command.quantity or 1, "product_query": query}
                for query in command.product_queries
                if query
            ]
        if not cart_requests:
            cart_requests = _extract_widget_cart_requests(state.user_goal)
        if not cart_requests:
            return None
        canonical_results = [
            self._lookup(state, str(cart_request.get("product_query") or "").strip())
            for cart_request in cart_requests
            if str(cart_request.get("product_query") or "").strip()
        ]
        return _build_multi_cart_tool_payload(canonical_results, cart_requests)

    def _resolve_clear_cart(self, state: WhatsAppCheckoutState) -> dict[str, Any] | None:
        if not _is_clear_cart_message(state.user_goal):
            return None
        return {
            "answer": "Listo, vacie el carrito.",
            "intent_label": "clear_cart",
            "workflow_stage": "browsing",
            "pending_next_step": "",
            "cart_action": {"type": "clear_cart"},
        }

    def _resolve_cart_status(self, state: WhatsAppCheckoutState, command: CheckoutCommand | None) -> dict[str, Any] | None:
        if not ((_is_cart_status_message(state.user_goal)) or (command is not None and command.intent == "cart_status")):
            return None
        items = enrich_cart_snapshot_prices(
            items=cart_snapshot_items(state.to_workflow_state_dict()),
            company_id=state.company_id,
            user_id=state.user_id,
            channel=state.channel,
            session_id=state.session_id,
            executor=self.executor,
        )
        answer = build_cart_status_answer_from_snapshot(items)
        return {
            "answer": answer,
            "intent_label": "cart_status",
            "workflow_stage": state.stage or "cart_building",
            "pending_next_step": state.pending_next_step or "cart_building",
            "workflow_action": {"type": "show_cart"},
        }
