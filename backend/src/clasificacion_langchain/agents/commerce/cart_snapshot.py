from __future__ import annotations

import json
import re
from typing import Any

from clasificacion_langchain.agents.commerce.tool_ports import CommerceToolExecutor


def cart_snapshot_items(workflow_state: dict[str, str] | None) -> list[dict[str, object]]:
    raw = str((workflow_state or {}).get("cart_snapshot") or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def build_cart_status_answer_from_snapshot(items: list[dict[str, object]]) -> str:
    if not items:
        return "Tu carrito esta vacio. Decime que producto queres llevar y te lo agrego."
    lines: list[str] = []
    subtotal = 0
    for item in items:
        name = str(item.get("name") or "Producto").strip() or "Producto"
        try:
            quantity = max(1, int(item.get("quantity") or 1))
        except (TypeError, ValueError):
            quantity = 1
        price_text = str(item.get("price") or "").strip()
        line = f"• {name} x{quantity}"
        digits = re.sub(r"[^0-9]", "", price_text)
        if digits:
            unit_price = int(digits)
            subtotal += unit_price * quantity
            line += f" — ${unit_price} c/u"
        elif price_text:
            line += f" — {price_text}"
        lines.append(line)
    answer = "Resumen de tu carrito:\n" + "\n".join(lines)
    if subtotal > 0:
        answer += f"\nSubtotal: ${subtotal}"
    return answer


def enrich_cart_snapshot_prices(
    *,
    items: list[dict[str, object]],
    company_id: str,
    user_id: str,
    channel: str,
    session_id: str,
    executor: CommerceToolExecutor,
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("price") or "").strip():
            enriched.append(item)
            continue
        product_name = str(item.get("name") or "").strip()
        if not product_name:
            enriched.append(item)
            continue
        try:
            result = executor.execute(
                tenant_id=company_id,
                tool="get_product_availability",
                channel=channel,
                user_id=user_id,
                arguments={"query": product_name, "limit": 1, "session_id": session_id},
            )
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            rows = data.get("items") if isinstance(data.get("items"), list) else []
            first = rows[0] if rows and isinstance(rows[0], dict) else {}
            price = str(first.get("price") or "").strip()
            if price:
                updated = dict(item)
                updated["price"] = price
                enriched.append(updated)
                continue
        except Exception:
            pass
        enriched.append(item)
    return enriched
