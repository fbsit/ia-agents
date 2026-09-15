from __future__ import annotations

import json
import logging
from typing import Any

from clasificacion_langchain.agents.commerce.extractors import (
    extract_widget_add_to_cart,
    extract_widget_remove_from_cart,
    extract_widget_set_cart_quantity,
    first_present_string,
)
from clasificacion_langchain.agents.commerce.recent_products import normalize_text
from clasificacion_langchain.agents.commerce.response_mapper import (
    build_generic_order_created_answer,
    format_canonical_tool_answer,
    normalize_catalog_product,
)


logger = logging.getLogger(__name__)


def _workflow_action(action_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": action_type, "payload": payload}


def resolve_cart_request_for_intent(
    *,
    user_message: str,
    intent: str,
    session_id: str | None,
) -> dict[str, Any] | None:
    normalized_intent = (intent or "").strip().lower()
    if normalized_intent == "add_to_cart":
        explicit = extract_widget_add_to_cart(user_message)
        if explicit:
            return explicit
    if normalized_intent == "remove_from_cart":
        explicit = extract_widget_remove_from_cart(user_message)
        if explicit:
            return explicit
    if normalized_intent == "set_cart_quantity":
        explicit = extract_widget_set_cart_quantity(user_message)
        if explicit:
            return explicit
    return None


def format_public_widget_tool_payload(
    result: dict[str, Any],
    *,
    user_message: str,
    intent_label: str | None,
    channel: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    if not result.get("ok"):
        return None

    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    tool = str(result.get("tool") or "").strip().lower()
    intent = (intent_label or "").strip().lower()

    if tool == "get_product_availability":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        safe_items = [item for item in items if isinstance(item, dict)]
        if not safe_items:
            return {"answer": "No encontre productos con ese criterio.", "products": []}

        products = []
        for item in safe_items[:3]:
            products.append(normalize_catalog_product(item))

        cart_request = resolve_cart_request_for_intent(
            user_message=user_message,
            intent=intent,
            session_id=session_id,
        )
        if cart_request and intent == "add_to_cart":
            first = products[0] if products else None
            if first and first.get("id"):
                cart_action = {
                    "type": "add_to_cart",
                    "item": {
                        "product_id": first["checkout_product_id"] or first["id"],
                        "checkout_product_id": first["checkout_product_id"] or first["id"],
                        "variant_id": first["variant_id"] or first["id"],
                        "quantity": cart_request["quantity"],
                        "name": first["name"],
                    },
                }
                logger.warning(
                    "commerce_tool_cart_action action=%s product=%s raw_products=%s",
                    cart_action,
                    first,
                    safe_items[0] if safe_items else None,
                )
                return {
                    "answer": f"Listo, agregue {cart_request['quantity']} {first['name']} al carrito. Si queres, seguimos con checkout cuando me digas \"quiero pagar\".",
                    "products": products,
                    "cart_action": cart_action,
                }

        remove_request = resolve_cart_request_for_intent(
            user_message=user_message,
            intent="remove_from_cart",
            session_id=session_id,
        )
        if remove_request:
            first = products[0] if products else None
            if first and first.get("id"):
                quantity = max(1, int(remove_request["quantity"]))
                cart_action = {
                    "type": "remove_from_cart",
                    "item": {
                        "product_id": first["checkout_product_id"] or first["id"],
                        "checkout_product_id": first["checkout_product_id"] or first["id"],
                        "variant_id": first["variant_id"] or first["id"],
                        "quantity": quantity,
                        "name": first["name"],
                    },
                }
                logger.warning(
                    "commerce_tool_cart_action action=%s product=%s raw_products=%s",
                    cart_action,
                    first,
                    safe_items[0] if safe_items else None,
                )
                return {
                    "answer": f"Listo, quite {quantity} {first['name']} del carrito.",
                    "products": products,
                    "cart_action": cart_action,
                    "workflow_stage": "cart_building",
                    "pending_next_step": "cart_building",
                }

        set_quantity_request = resolve_cart_request_for_intent(
            user_message=user_message,
            intent="set_cart_quantity",
            session_id=session_id,
        )
        if set_quantity_request:
            first = products[0] if products else None
            if first and first.get("id"):
                quantity = max(1, int(set_quantity_request["quantity"]))
                cart_action = {
                    "type": "set_cart_quantity",
                    "item": {
                        "product_id": first["checkout_product_id"] or first["id"],
                        "checkout_product_id": first["checkout_product_id"] or first["id"],
                        "variant_id": first["variant_id"] or first["id"],
                        "quantity": quantity,
                        "name": first["name"],
                    },
                }
                logger.warning(
                    "commerce_tool_cart_action action=%s product=%s raw_products=%s",
                    cart_action,
                    first,
                    safe_items[0] if safe_items else None,
                )
                return {
                    "answer": f"Listo, deje {first['name']} en {quantity} unidades en el carrito.",
                    "products": products,
                    "cart_action": cart_action,
                    "workflow_stage": "cart_building",
                    "pending_next_step": "cart_building",
                }

        availability_tokens = ["tienen ", "tenes ", "tienes ", "tiene ", "hay ", "stock", "disponible", "precio", "cuesta"]
        normalized_message = (user_message or "").strip().lower()

        if any(token in normalized_message for token in availability_tokens):
            first = products[0]
            answer = f"Si, {first['name']} esta disponible. Precio: ${first['price']}. Stock: {first['stock']}."
            remaining = [f"• {p['name']} — ${p['price']}" for p in products[1:3] if p.get('price') and p.get('name')]
            if remaining:
                answer += "\nTambien tengo:\n" + "\n".join(remaining)
            return {
                "answer": answer,
                "products": products[:3],
                "focused_product": first["name"],
                "workflow_stage": "product_lookup",
                "pending_next_step": "add_to_cart",
                "awaiting_slot": "quantity_or_action",
            }

        formatted = "\n".join(f"• {p['name']} — ${p['price']}" for p in products[:5] if p.get('name'))
        return {
            "answer": f"Te paso las opciones que tengo:\n{formatted}" if formatted else "No encontre productos.",
            "products": products,
            "focused_product": products[0]["name"] if products else "",
            "workflow_stage": "product_lookup",
            "pending_next_step": "add_to_cart",
            "awaiting_slot": "quantity_or_action",
        }

    if tool == "get_shipping_options":
        options = data.get("options") if isinstance(data.get("options"), list) else []
        names = [str((o or {}).get("name") or "").strip() for o in options if isinstance(o, dict)]
        names = [name for name in names if name]
        return {
            "answer": f"Opciones de despacho: {', '.join(names)}." if names else "No hay opciones de despacho activas ahora.",
        }

    if tool == "get_payment_options":
        options = data.get("options") if isinstance(data.get("options"), list) else []
        names = [str((o or {}).get("name") or "").strip() for o in options if isinstance(o, dict)]
        names = [name for name in names if name]
        normalized_message = (user_message or "").strip().lower()
        normalized_channel = (channel or "").strip().lower()
        if normalized_channel in {"widget_web", "web", "widget_public"} and any(
            token in normalized_message
            for token in ["quiero pagar", "ir a pagar", "pagar", "checkout", "finalizar compra", "terminar compra", "comprar ahora"]
        ):
            return {
                "answer": "Te llevo al checkout web para completar despacho y pago.",
                "redirect_to": "/cart?checkout=1&source=agent",
            }
        return {
            "answer": f"Medios de pago: {', '.join(names)}." if names else "No hay medios de pago activos ahora.",
        }

    if tool == "get_order_status":
        order_reference = first_present_string(data, ["order_reference", "order_id", "id", "number"])
        status = first_present_string(data, ["status", "order_status", "state"])
        tracking_url = first_present_string(data, ["tracking_url", "tracking_link"])
        answer_parts: list[str] = []
        if order_reference:
            answer_parts.append(f"Pedido {order_reference}")
        if status:
            answer_parts.append(f"estado {status}")
        answer = ", ".join(answer_parts) if answer_parts else "Encontre informacion del pedido."
        if tracking_url:
            answer += f" Puedes seguirlo aqui: {tracking_url}."
        payload = {"answer": answer}
        if tracking_url and (channel or "").strip().lower() in {"widget_web", "web", "widget_public", "api", "api_internal"}:
            payload["redirect_to"] = tracking_url
        return payload

    if tool == "create_payment_link":
        payment_url = first_present_string(data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
        expires_at = first_present_string(data, ["expires_at", "expiration", "expires_on"])
        if payment_url:
            answer = "Listo, te dejo el link de pago para cerrar la compra."
            if expires_at:
                answer += f" Vigencia: {expires_at}."
            payload = {
                "answer": answer,
                "redirect_to": payment_url,
                "workflow_stage": "browsing",
                "checkout_stage": "completed",
                "pending_next_step": "",
                "reset_workflow": True,
                "workflow_action": _workflow_action(
                    "payment_link_ready",
                    payment_url=payment_url,
                    expires_at=expires_at,
                    close_conversation=True,
                ),
            }
            return payload
        return {"answer": "Pude preparar la accion de pago, pero el proveedor no devolvio un link utilizable."}

    if tool == "create_order_draft":
        draft_reference = first_present_string(data, ["draft_id", "order_id", "order_reference", "id", "number"])
        payment_url = first_present_string(data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
        total = first_present_string(data, ["total", "amount", "grand_total"])
        answer = build_generic_order_created_answer(data)
        payload = {"answer": answer}
        if payment_url:
            payload["redirect_to"] = payment_url
        payload["workflow_stage"] = "browsing"
        payload["checkout_stage"] = "completed"
        payload["pending_next_step"] = ""
        payload["reset_workflow"] = True
        payload["workflow_action"] = _workflow_action(
            "order_created",
            order_reference=draft_reference,
            payment_url=payment_url,
            total=total,
            close_conversation=True,
        )
        return payload

    tool_answer = format_canonical_tool_answer(result)
    if not tool_answer:
        return None
    return {"answer": tool_answer}


def build_multi_cart_tool_payload(
    canonical_results: list[dict[str, Any]],
    cart_requests: list[dict[str, Any]],
) -> dict[str, Any] | None:
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
        checkout_product_id = str(first.get("code") or first.get("id") or "").strip()
        variant_id = str(first.get("id") or "").strip()
        name = str(first.get("name") or "Producto").strip() or "Producto"

        logger.warning(
            "commerce_cart_build_raw raw_item=%s cart_request=%s",
            {k: first.get(k) for k in ("id", "code", "name", "price", "available_units", "image_url") if k in first},
            cart_request,
        )

        if not product_id:
            logger.warning(
                "commerce_cart_build_skip reason=no_product_id raw_item=%s cart_request=%s",
                {k: first.get(k) for k in ("id", "code", "name") if k in first},
                cart_request,
            )
            continue

        cart_action_item = {
            "product_id": checkout_product_id or product_id,
            "checkout_product_id": checkout_product_id or product_id,
            "variant_id": variant_id or product_id,
            "quantity": int(cart_request.get("quantity") or 1),
            "name": name,
        }
        cart_actions.append({"type": "add_to_cart", "item": cart_action_item})

        logger.warning(
            "commerce_cart_build_action item=%s raw_id=%s raw_code=%s raw_name=%s",
            cart_action_item,
            first.get("id"),
            first.get("code"),
            first.get("name"),
        )

        for item in safe_items[:3]:
            current_id = str(item.get("id") or "").strip()
            if not current_id or current_id in seen_products:
                continue
            seen_products.add(current_id)
            products.append(
                {
                    "id": current_id,
                    "checkout_product_id": str(item.get("code") or item.get("id") or "").strip(),
                    "variant_id": str(item.get("id") or "").strip(),
                    "name": str(item.get("name") or "Producto").strip(),
                    "price": str(item.get("price") or "N/D").strip(),
                    "stock": str(item.get("available_units") or "0").strip(),
                    "image_url": str(item.get("image_url") or "").strip() or None,
                }
            )

    if not cart_actions:
        return None

    summary = " y ".join(
        f"{action['item']['quantity']} {action['item']['name']}" for action in cart_actions if isinstance(action, dict)
    )
    return {
        "answer": f"Listo, agregue {summary} al carrito. Si queres, seguimos con checkout cuando me digas \"quiero pagar\".",
        "intent_label": "add_to_cart",
        "cart_action": cart_actions[0],
        "cart_actions": cart_actions,
        "products": products[:6],
        "focused_product": str(((cart_actions[0].get("item") or {}).get("name") or "")).strip(),
        "workflow_stage": "cart_building",
        "pending_next_step": "shipping_selection",
        "awaiting_slot": "shipping_method",
    }


def build_multi_product_lookup_payload(
    canonical_results: list[dict[str, Any]],
    queries: list[str],
    user_message: str,
    channel: str | None = None,
) -> dict[str, Any] | None:
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
            normalized_product = normalize_catalog_product(item)
            normalized_product["query"] = query
            products.append(normalized_product)

    if not products:
        return None

    normalized_message = normalize_text(user_message)
    if any(token in normalized_message for token in ["stock", "disponible", "precio", "cuesta", "tienen", "tienes", "tiene", "tenian", "hay"]):
        answer = "Si, encontre estas opciones:"
    else:
        answer = "Te paso las opciones:"

    if products:
        formatted = "\n".join(f"• {p['name']} — ${p['price']}" for p in products[:5] if p.get('name'))
        answer = f"{answer}\n{formatted}"

    return {
        "answer": answer,
        "products": products[:6],
        "focused_product": products[0]["name"] if products else "",
        "workflow_stage": "product_lookup",
        "pending_next_step": "add_to_cart",
        "awaiting_slot": "quantity_or_action",
    }


def build_recipe_recommendation_payload(
    recipe_plan: dict[str, Any],
    ingredient_results_by_query: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    recipes = recipe_plan.get("recipes") if isinstance(recipe_plan.get("recipes"), list) else []
    if not recipes:
        return None

    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    recipe_lines: list[str] = []

    for recipe in recipes[:2]:
        if not isinstance(recipe, dict):
            continue
        recipe_name = str(recipe.get("name") or "Receta").strip() or "Receta"
        reason = str(recipe.get("reason") or "").strip()
        ingredient_queries = [str(item).strip() for item in (recipe.get("ingredient_queries") or []) if str(item).strip()]
        available_names: list[str] = []

        for ingredient_query in ingredient_queries[:6]:
            result = ingredient_results_by_query.get(ingredient_query)
            if not isinstance(result, dict) or not result.get("ok"):
                continue
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            items = data.get("items") if isinstance(data.get("items"), list) else []
            safe_items = [item for item in items if isinstance(item, dict)]
            if not safe_items:
                continue
            first = safe_items[0]
            available_names.append(str(first.get("name") or ingredient_query).strip() or ingredient_query)
            for item in safe_items[:1]:
                product_id = str(item.get("id") or "").strip()
                if not product_id or product_id in seen:
                    continue
                seen.add(product_id)
                products.append(normalize_catalog_product(item))

        if available_names:
            recipe_lines.append(f"- {recipe_name}: {reason or 'Te puede servir'} Ingredientes sugeridos: {', '.join(available_names[:5])}.")

    if not recipe_lines:
        return None

    return {
        "answer": "Te recomiendo estas recetas con productos que podrias llevar:\n" + "\n".join(recipe_lines),
        "products": products[:6],
    }


def payload_product_names(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    products = payload.get("products") if isinstance(payload.get("products"), list) else []
    names: list[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        name = str(product.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def payload_focused_product(payload: dict[str, Any] | None) -> str | None:
    names = payload_product_names(payload)
    if names:
        return names[0]
    return None


def payload_awaiting_slot(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    explicit = str(payload.get("awaiting_slot") or "").strip()
    if explicit:
        return explicit
    pending_next_step = str(payload.get("pending_next_step") or "").strip().lower()
    workflow_stage = str(payload.get("workflow_stage") or "").strip().lower()
    if pending_next_step == "add_to_cart" or workflow_stage == "product_lookup":
        return "quantity_or_action"
    if pending_next_step == "shipping_selection":
        return "shipping_method"
    if pending_next_step == "payment_selection":
        return "payment_method"
    return None


def payload_cart_actions(payload: dict[str, Any] | None) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        return []
    actions = payload.get("cart_actions") if isinstance(payload.get("cart_actions"), list) else None
    if actions:
        return [action for action in actions if isinstance(action, dict)]
    action = payload.get("cart_action") if isinstance(payload.get("cart_action"), dict) else None
    return [action] if action else []


def payload_saved_addresses(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    addresses = payload.get("saved_addresses") if isinstance(payload.get("saved_addresses"), list) else None
    if addresses is None:
        return None
    safe_addresses = [address for address in addresses if isinstance(address, dict)]
    return json.dumps(safe_addresses, ensure_ascii=False, separators=(",", ":")) if safe_addresses else ""
