from __future__ import annotations

from typing import Any

from clasificacion_langchain.agents.commerce.extractors import (
    extract_order_lines_from_result_data,
    first_present_string,
)
from clasificacion_langchain.agents.commerce.recent_products import normalize_text
from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState


def map_checkout_response_payload(
    payload: dict[str, Any] | None,
    state: WhatsAppCheckoutState,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    mapped = dict(payload)
    mapped.setdefault("workflow_stage", state.stage)
    if state.checkout_stage:
        mapped.setdefault("checkout_stage", state.checkout_stage)
    if state.pending_next_step:
        mapped.setdefault("pending_next_step", state.pending_next_step)
    if state.awaiting_slot:
        mapped.setdefault("awaiting_slot", state.awaiting_slot)
    if state.workflow_expired:
        mapped.setdefault("workflow_expired", True)
    if state.workflow_timeout_confirmation:
        mapped.setdefault("workflow_timeout_confirmation", True)
    if "cart_action" in mapped and "cart_actions" not in mapped and isinstance(mapped.get("cart_action"), dict):
        mapped["cart_actions"] = [mapped["cart_action"]]
    return mapped


def normalize_catalog_product(item: dict[str, Any]) -> dict[str, Any]:
    product_id = first_present_string(item, ["id", "product_id", "variant_id", "sku", "code"])
    checkout_product_id = first_present_string(item, ["code", "checkout_product_id", "product_id", "id", "sku"])
    variant_id = first_present_string(item, ["variant_id", "id", "product_id", "sku", "code"])
    image_url = first_present_string(item, ["image_url", "image", "imageUrl", "thumbnail", "thumbnail_url", "photo"])
    price = first_present_string(item, ["price", "unit_price", "sale_price", "amount", "value"])
    stock = first_present_string(item, ["available_units", "stock", "quantity", "available", "inventory"])
    name = first_present_string(item, ["name", "title", "product_name", "label"]) or "Producto"
    return {
        "id": product_id,
        "checkout_product_id": checkout_product_id or product_id,
        "variant_id": variant_id or product_id,
        "name": name,
        "price": price or "N/D",
        "stock": stock or "0",
        "image_url": image_url or None,
    }


def format_canonical_tool_answer(result: dict[str, Any]) -> str | None:
    if not result.get("ok"):
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    tool = str(result.get("tool") or "")
    if tool == "get_product_availability":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        if not items:
            return "No encontré productos con ese criterio."
        first = normalize_catalog_product(items[0] if isinstance(items[0], dict) else {})
        return f"Sí, {first['name']} está disponible. Precio: {first['price']}. Stock: {first['stock']}."
    if tool == "get_shipping_options":
        options = data.get("options") if isinstance(data.get("options"), list) else []
        names = [str((o or {}).get("name") or "").strip() for o in options if isinstance(o, dict)]
        names = [n for n in names if n]
        return f"Opciones de despacho: {', '.join(names)}." if names else "No hay opciones de despacho activas ahora."
    if tool == "get_payment_options":
        options = data.get("options") if isinstance(data.get("options"), list) else []
        names = [str((o or {}).get("name") or "").strip() for o in options if isinstance(o, dict)]
        names = [n for n in names if n]
        return f"Medios de pago: {', '.join(names)}." if names else "No hay medios de pago activos ahora."
    if tool == "get_order_status":
        status = first_present_string(data, ["status", "order_status", "state"])
        order_reference = first_present_string(data, ["order_reference", "order_id", "id", "number"])
        tracking = first_present_string(data, ["tracking_url", "tracking_link"])
        parts = []
        if order_reference:
            parts.append(f"Pedido {order_reference}")
        if status:
            parts.append(f"estado {status}")
        answer = ", ".join(parts) if parts else "Encontre informacion del pedido."
        if tracking:
            answer += f" Seguimiento: {tracking}."
        return answer
    if tool == "create_payment_link":
        url = first_present_string(data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
        if url:
            return f"Listo, ya tengo tu link de pago: {url}"
        return "Pude generar la accion de pago, pero el proveedor no devolvio un link utilizable."
    if tool == "create_order_draft":
        draft_reference = first_present_string(data, ["draft_id", "order_id", "order_reference", "id", "number"])
        payment_url = first_present_string(data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
        answer = (
            f"Listo, deje creada la orden borrador {draft_reference}." if draft_reference else "Listo, deje creada la orden borrador."
        )
        if payment_url:
            answer += f" Si quieres, puedes pagar desde aqui: {payment_url}"
        return answer
    return None


def option_names_from_result(result: dict[str, Any]) -> list[str]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    options = data.get("options") if isinstance(data.get("options"), list) else []
    names = [str((option or {}).get("name") or "").strip() for option in options if isinstance(option, dict)]
    return [name for name in names if name]


def pickup_option_names_from_result(result: dict[str, Any]) -> list[str]:
    names = option_names_from_result(result)
    pickup_names = [
        name for name in names
        if any(token in normalize_text(name) for token in ["retiro", "pickup", "tienda", "sucursal", "local"])
    ]
    concrete_pickup_names = [
        name for name in pickup_names
        if normalize_text(name) not in {"retiro en tienda", "retiro tienda", "pickup", "retiro", "tienda"}
    ]
    return concrete_pickup_names


def build_payment_options_answer(names: list[str]) -> str:
    if not names:
        return "No hay medios de pago activos ahora."
    return f"Medios de pago: {', '.join(names)}. Cual prefieres?"


def build_order_created_answer(
    *,
    workflow_state: dict[str, str] | None,
    checkout_items: list[dict[str, Any]],
    result_data: dict[str, Any],
) -> str:
    order_reference = first_present_string(result_data, ["draft_id", "order_id", "order_reference", "id", "number"])
    payment_url = first_present_string(result_data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
    total = first_present_string(result_data, ["total", "amount", "grand_total"])
    payment_preference = str((workflow_state or {}).get("payment_preference") or "").strip()
    invoice_type = str((workflow_state or {}).get("invoice_type") or "").strip()
    pickup_location = str((workflow_state or {}).get("pickup_location_label") or "").strip()
    delivery_address = str((workflow_state or {}).get("delivery_address") or "").strip()

    lines = ["Perfecto, ya deje registrada tu compra."]
    if order_reference:
        lines.append(f"Orden: {order_reference}")
    if checkout_items:
        product_lines = []
        for item in checkout_items:
            name = str(item.get("name") or item.get("product_name") or "Producto").strip() or "Producto"
            quantity = int(item.get("quantity") or 1)
            product_lines.append(f"• {name} x{quantity}")
        if product_lines:
            lines.append("Detalle:")
            lines.extend(product_lines[:8])
    if pickup_location:
        lines.append(f"Retiro: {pickup_location}")
    elif delivery_address:
        lines.append(f"Despacho: {delivery_address}")
    if payment_preference:
        lines.append(f"Pago: {payment_preference}")
    if invoice_type:
        lines.append(f"Documento: {invoice_type}")
    if total:
        lines.append(f"Total referencial: {total}")
    if payment_url:
        lines.append("Tambien deje listo el siguiente paso de pago.")
    lines.append("Gracias por tu compra.")
    return "\n".join(lines)


def build_generic_order_created_answer(result_data: dict[str, Any]) -> str:
    order_reference = first_present_string(result_data, ["draft_id", "order_id", "order_reference", "id", "number"])
    payment_url = first_present_string(result_data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
    total = first_present_string(result_data, ["total", "amount", "grand_total"])
    lines = ["Perfecto, ya deje registrada tu compra."]
    if order_reference:
        lines.append(f"Orden: {order_reference}")
    order_lines = extract_order_lines_from_result_data(result_data)
    if order_lines:
        lines.append("Detalle:")
        for row in order_lines[:8]:
            lines.append(f"• {row['name']} x{row['quantity']}")
    if total:
        lines.append(f"Total referencial: {total}")
    if payment_url:
        lines.append("Tambien deje listo el siguiente paso de pago.")
    lines.append("Gracias por tu compra.")
    return "\n".join(lines)
