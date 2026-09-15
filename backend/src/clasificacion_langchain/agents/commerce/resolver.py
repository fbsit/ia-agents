from __future__ import annotations

import logging

from dataclasses import dataclass
from typing import Any, Callable

from clasificacion_langchain.agents.commerce.cart_snapshot import cart_snapshot_items
from clasificacion_langchain.agents.commerce.checkout_link import (
    build_web_checkout_redirect,
    describe_web_checkout_answer,
)
from clasificacion_langchain.agents.commerce.commands import CheckoutCommand
from clasificacion_langchain.agents.commerce.extractors import (
    canonical_tool_succeeded,
    is_checkout_redirect_channel,
    is_email_message,
)
from clasificacion_langchain.agents.commerce.lookup_cart import LookupCartResolver
from clasificacion_langchain.agents.commerce.recent_products import normalize_text
from clasificacion_langchain.agents.commerce.resume_timeout import (
    resolve_resume_timeout_preflight,
)
from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState
from clasificacion_langchain.agents.commerce.tool_ports import CommerceToolExecutor

logger = logging.getLogger(__name__)


FallbackResolver = Callable[[WhatsAppCheckoutState, CheckoutCommand | None], dict[str, Any] | None]


def _is_affirmative(message: str) -> bool:
    return normalize_text(message) in {
        "si",
        "si confirmo",
        "confirmo",
        "confirmar",
        "si esta correcto",
        "correcto",
    }


def _is_email(message: str) -> bool:
    import re

    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(message or "").strip()))


def _is_numeric_code(message: str) -> bool:
    clean = str(message or "").strip()
    return clean.isdigit() and 4 <= len(clean) <= 8


def _extract_saved_addresses(raw: str | None) -> list[dict[str, str]]:
    import json

    clean = str(raw or "").strip()
    if not clean:
        return []
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, str]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or f"Direccion {index}").strip() or f"Direccion {index}"
        address = str(item.get("address") or item.get("full_address") or item.get("street") or "").strip()
        if address:
            rows.append({"label": label, "address": address})
    return rows


def _match_saved_address(message: str, addresses: list[dict[str, str]]) -> str:
    normalized = normalize_text(message)
    if not normalized:
        return ""
    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(addresses):
            return addresses[index - 1]["address"]
    for row in addresses:
        label = normalize_text(row.get("label") or "")
        address = normalize_text(row.get("address") or "")
        if normalized == label or normalized == address or normalized in label:
            return row["address"]
    return ""


def _order_summary_answer(state: WhatsAppCheckoutState) -> str:
    lines = ["Perfecto, te dejo el resumen para confirmar:"]
    if state.selected_products:
        lines.append(f"Productos: {', '.join(state.selected_products)}.")
    if state.pickup_location_label:
        lines.append(f"Retiro: {state.pickup_location_label}.")
    elif state.shipping_preference:
        lines.append(f"Despacho/retiro: {state.shipping_preference}.")
    if state.delivery_address:
        lines.append(f"Direccion de despacho: {state.delivery_address}.")
    if state.payment_preference:
        lines.append(f"Pago: {state.payment_preference}.")
    if state.invoice_type:
        lines.append(f"Documento: {state.invoice_type}.")
    if state.invoice_type == "factura" and state.invoice_address:
        lines.append(f"Direccion de factura: {state.invoice_address}.")
    lines.append("Si esta correcto, confirmamelo y te genero el siguiente paso.")
    return "\n".join(lines)


def _completed_answer(state: WhatsAppCheckoutState, result_data: dict[str, Any]) -> str:
    def first(data: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    order_reference = first(result_data, ["order_reference", "order_id", "id", "number", "draft_id"])
    total = first(result_data, ["total", "amount", "grand_total"])
    payment_url = first(result_data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
    lines = ["Perfecto, ya deje registrada tu compra."]
    if order_reference:
        lines.append(f"Orden: {order_reference}")
    cart_items = cart_snapshot_items(state.to_workflow_state_dict())
    if cart_items:
        lines.append("Detalle:")
        for item in cart_items[:8]:
            quantity = int(item.get("quantity") or 1)
            lines.append(f"• {item.get('name') or 'Producto'} x{quantity}")
    elif state.selected_products:
        lines.append("Detalle:")
        for name in state.selected_products[:8]:
            lines.append(f"• {name}")
    if state.pickup_location_label:
        lines.append(f"Retiro: {state.pickup_location_label}")
    elif state.delivery_address:
        lines.append(f"Despacho: {state.delivery_address}")
    if state.payment_preference:
        lines.append(f"Pago: {state.payment_preference}")
    if state.invoice_type:
        lines.append(f"Documento: {state.invoice_type}")
    if total:
        lines.append(f"Total referencial: {total}")
    if payment_url:
        lines.append("Tambien deje listo el siguiente paso de pago.")
    lines.append("Gracias por tu compra.")
    return "\n".join(lines)


@dataclass
class CheckoutWorkflowResolver:
    executor: CommerceToolExecutor
    fallback: FallbackResolver
    recent_products_provider: Callable[[str], list[dict[str, Any]]] | None = None
    clear_timeout_markers: Callable[[], None] | None = None
    is_affirmative_message: Callable[[str], bool] = _is_affirmative
    is_greeting_message: Callable[[str], bool] = lambda _message: False

    def resolve(self, state: WhatsAppCheckoutState, command: CheckoutCommand | None) -> dict[str, Any] | None:
        resume_timeout_payload = resolve_resume_timeout_preflight(
            state=state,
            clear_timeout_markers=self.clear_timeout_markers,
            is_affirmative_message=self.is_affirmative_message,
            is_greeting_message=self.is_greeting_message,
        )
        if resume_timeout_payload.handled:
            return resume_timeout_payload.payload
        # Lookup/cart now belongs to the workflow package first.
        # Checkout-specific handling only runs if the migrated lookup/cart slice did not handle the turn.
        lookup_cart_resolver = LookupCartResolver(
            executor=self.executor,
            recent_products_provider=self.recent_products_provider or (lambda _session_id: []),
        )
        lookup_payload = lookup_cart_resolver.resolve(state, command)
        if lookup_payload.handled:
            return lookup_payload.payload
        payload = self._resolve_checkout(state, command)
        if payload is not None:
            return payload
        return self.fallback(state, command)

    def _resolve_checkout(self, state: WhatsAppCheckoutState, command: CheckoutCommand | None) -> dict[str, Any] | None:
        normalized_goal = normalize_text(state.user_goal)

        if state.checkout_stage == "auth_pending":
            if _is_email(state.user_goal):
                self.executor.execute(
                    tenant_id=state.company_id,
                    tool="send_verification_code",
                    channel=state.channel,
                    user_id=state.user_id,
                    arguments={"email": state.user_goal.strip()},
                )
                return {
                    "answer": f"Te enviamos un codigo de verificacion a {state.user_goal.strip()}. Ingresalo aca para continuar.",
                    "intent_label": "checkout_otp_sent",
                    "workflow_stage": "checkout_auth",
                    "checkout_stage": "otp_pending",
                    "pending_next_step": "otp_verification",
                    "awaiting_slot": "otp_code",
                    "otp_email": state.user_goal.strip(),
                }
            return {
                "answer": "Para seguir con el pago necesito que inicies sesion primero. Escribe tu correo electronico para enviarte un codigo de verificacion.",
                "intent_label": "checkout_auth_needed",
                "workflow_stage": "checkout_auth",
                "checkout_stage": "auth_pending",
                "pending_next_step": "auth_confirmation",
                "awaiting_slot": "otp_email",
            }

        if state.checkout_stage == "otp_pending" or state.pending_next_step == "otp_verification":
            if state.otp_email and _is_numeric_code(state.user_goal):
                verify_result = self.executor.execute(
                    tenant_id=state.company_id,
                    tool="verify_verification_code",
                    channel=state.channel,
                    user_id=state.user_id,
                    arguments={"email": state.otp_email, "code": state.user_goal.strip()},
                )
                if not canonical_tool_succeeded(verify_result, expected_statuses={"verified", "valid", "ok", "success"}):
                    return {
                        "answer": "El codigo ingresado no es valido o expiro. Intenta de nuevo o escribe tu correo para reenviar el codigo.",
                        "intent_label": "checkout_otp_invalid",
                        "workflow_stage": "checkout_auth",
                        "checkout_stage": "otp_pending",
                        "pending_next_step": "otp_verification",
                        "awaiting_slot": "otp_code",
                        "otp_email": state.otp_email,
                    }
                # Sesion de cliente en ClubHx (customer_id) para que el pedido quede a su nombre.
                try:
                    self.executor.execute(
                        tenant_id=state.company_id,
                        tool="login_with_code",
                        channel=state.channel,
                        user_id=state.user_id,
                        arguments={"email": state.otp_email, "code": state.user_goal.strip()},
                    )
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "answer": "Perfecto, ya estas autenticado. Ahora dime si prefieres retiro en tienda o despacho.",
                    "intent_label": "checkout_auth_confirmed",
                    "workflow_stage": "shipping_selection",
                    "checkout_stage": "shipping_method_pending",
                    "pending_next_step": "shipping_selection",
                    "awaiting_slot": "shipping_method",
                }
            if is_email_message(state.user_goal):
                email = state.user_goal.strip()
                sent = self.executor.execute(
                    tenant_id=state.company_id,
                    tool="send_verification_code",
                    channel=state.channel,
                    user_id=state.user_id,
                    arguments={"email": email},
                )
                if canonical_tool_succeeded(sent, expected_statuses={"sent", "ok", "success"}):
                    return {
                        "answer": f"Te reenvie el codigo de verificacion a {email}. Ingresalo aca para continuar.",
                        "intent_label": "checkout_otp_sent",
                        "workflow_stage": "checkout_auth",
                        "checkout_stage": "otp_pending",
                        "pending_next_step": "otp_verification",
                        "awaiting_slot": "otp_code",
                        "otp_email": email,
                    }
            # Ni codigo ni correo (p. ej. una pregunta de despacho): que responda el conocimiento.
            # El checkout sigue esperando el codigo; no se reinicia.
            return None

        payment_intent = command.intent if command else ""
        wants_checkout_progression = payment_intent in {"checkout_continue", "payment_options", "create_payment_link", "create_order_draft"}
        if not wants_checkout_progression:
            wants_checkout_progression = any(
                token in normalized_goal
                for token in ["quiero pagar", "pagar", "medio de pago", "medios de pago", "mercado pago", "transferencia", "link de pago"]
            )
        if wants_checkout_progression and is_checkout_redirect_channel(state.channel):
            # Web nunca completa OTP/direccion/pago por chat: arma el link real
            # del carrito y que el cliente inicie sesion y pague en el
            # storefront. Sin esto, este mismo "quiero pagar" caia en el
            # requerimiento de OTP de mas abajo, pensado para WhatsApp.
            checkout_link = build_web_checkout_redirect(
                client=self.executor.client,
                workflow_state=state.to_workflow_state_dict(),
                session_id=state.session_id,
            )
            if checkout_link is None:
                return {
                    "answer": "No pude armar el link de compra ahora mismo. Decime que producto queres y seguimos por aca.",
                    "intent_label": "checkout_web",
                }
            return {
                "answer": describe_web_checkout_answer(checkout_link),
                "intent_label": "checkout_web",
                "workflow_stage": "checkout_ready",
                "checkout_stage": "web_checkout_redirect",
                "pending_next_step": "payment_selection",
                "redirect_to": checkout_link.url,
                "workflow_action": {"type": "open_checkout", "payload": {"redirect_to": checkout_link.url}},
            }
        if (
            wants_checkout_progression
            and not state.customer_authenticated
            and (
                state.checkout_stage in {"payment_method_pending", "document_type_pending", "order_summary_pending"}
                or state.pending_next_step in {"payment_selection", "document_type", "order_confirmation"}
                or state.stage in {"payment_selection", "order_review"}
            )
        ):
            return {
                "answer": "Para seguir con el pago necesito que inicies sesion primero. Escribe tu correo electronico para enviarte un codigo de verificacion.",
                "intent_label": "checkout_auth_needed",
                "workflow_stage": "checkout_auth",
                "checkout_stage": "auth_pending",
                "pending_next_step": "auth_confirmation",
                "awaiting_slot": "otp_email",
            }

        if command and command.intent == "checkout_continue" and not state.customer_authenticated:
            return {
                "answer": "Para seguir con el pago necesito que inicies sesion primero. Escribe tu correo electronico para enviarte un codigo de verificacion.",
                "intent_label": "checkout_auth_needed",
                "workflow_stage": "checkout_auth",
                "checkout_stage": "auth_pending",
                "pending_next_step": "auth_confirmation",
                "awaiting_slot": "otp_email",
            }

        if state.checkout_stage == "shipping_method_pending":
            if command and command.shipping_method == "pickup" or "retiro" in normalized_goal:
                payment_result = self.executor.execute(
                    tenant_id=state.company_id,
                    tool="get_payment_options",
                    channel=state.channel,
                    user_id=state.user_id,
                    arguments={"session_id": state.session_id},
                )
                option_names = [
                    str((option or {}).get("name") or "").strip()
                    for option in ((payment_result.get("data") or {}).get("options") or [])
                    if isinstance(option, dict)
                ]
                answer = "Perfecto, dejo retiro en tienda."
                if option_names:
                    answer += f" Medios de pago: {', '.join([n for n in option_names if n])}. Cual prefieres?"
                return {
                    "answer": answer,
                    "intent_label": "pickup_selected",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "payment_method_pending",
                    "pending_next_step": "payment_selection",
                    "awaiting_slot": "payment_method",
                    "pickup_location_label": "retiro en tienda",
                }

        if state.checkout_stage == "payment_method_pending" or state.pending_next_step == "payment_selection":
            payment_method = (command.payment_method if command else "") or ("mercado_pago" if "mercado pago" in normalized_goal else "transferencia" if "transferencia" in normalized_goal else "")
            if payment_method:
                human_name = "Mercado Pago" if payment_method == "mercado_pago" else "Transferencia bancaria"
                return {
                    "answer": f"Perfecto, dejo {human_name} como medio de pago. Ahora dime si necesitas boleta o factura.",
                    "intent_label": "payment_method_selected",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "document_type_pending",
                    "pending_next_step": "document_type",
                    "awaiting_slot": "document_type",
                    "payment_preference": payment_method,
                }

        document_type_pending = state.checkout_stage == "document_type_pending" or state.pending_next_step == "document_type"
        if document_type_pending:
            invoice_type = state.invoice_type or (command.invoice_type if command else "")
            invoice_type = invoice_type or ("boleta" if "boleta" in normalized_goal else "factura" if "factura" in normalized_goal else "")
            if invoice_type == "boleta":
                state.invoice_type = "boleta"
                return {
                    "answer": "Perfecto, se emite boleta. Si esta correcto, confirmamelo y te genero el siguiente paso.",
                    "intent_label": "invoice_summary_ready",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "order_summary_pending",
                    "pending_next_step": "order_confirmation",
                    "invoice_type": "boleta",
                }
            if invoice_type == "factura":
                saved_addresses = _extract_saved_addresses(state.saved_addresses)
                if saved_addresses:
                    lines = ["Puedo usar una de tus direcciones guardadas para la factura:"]
                    lines.extend(f"{index}. {row['label']}: {row['address']}" for index, row in enumerate(saved_addresses, start=1))
                    lines.append("Dime el numero, el nombre o escribeme una direccion nueva.")
                    answer = "\n".join(lines)
                elif state.delivery_address:
                    answer = f"La direccion de facturacion es la misma de despacho?\n{state.delivery_address}"
                else:
                    answer = "Dime la direccion de facturacion (calle, numero, comuna)."
                return {
                    "answer": answer,
                    "intent_label": "invoice_address_pending",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "invoice_address_pending",
                    "pending_next_step": "invoice_address",
                    "awaiting_slot": "invoice_address",
                    "invoice_type": "factura",
                }

        if state.checkout_stage == "invoice_address_pending":
            saved_addresses = _extract_saved_addresses(state.saved_addresses)
            chosen = _match_saved_address(state.user_goal, saved_addresses)
            invoice_address = chosen or (state.delivery_address if _is_affirmative(state.user_goal) and state.delivery_address else state.user_goal.strip())
            if invoice_address:
                return {
                    "answer": f"Perfecto, usare direccion de factura: {invoice_address}.\nSi esta correcto, confirmamelo y te genero el siguiente paso.",
                    "intent_label": "invoice_summary_ready",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "order_summary_pending",
                    "pending_next_step": "order_confirmation",
                    "invoice_type": "factura",
                    "invoice_address": invoice_address,
                }

        if state.checkout_stage == "order_summary_pending" or state.pending_next_step == "order_confirmation":
            if _is_affirmative(state.user_goal):
                # Items reales del carrito (ids de ClubHx). Solo si no hay snapshot se cae a los nombres.
                items = [
                    {
                        "product_id": str(item.get("product_id") or "").strip(),
                        "checkout_product_id": str(item.get("checkout_product_id") or item.get("product_id") or "").strip(),
                        "variant_id": str(item.get("variant_id") or item.get("product_id") or "").strip(),
                        "quantity": max(1, int(item.get("quantity") or 1)),
                        "name": str(item.get("name") or "").strip(),
                    }
                    for item in cart_snapshot_items(state.to_workflow_state_dict())
                    if str(item.get("product_id") or "").strip()
                ]
                if not items:
                    for index, name in enumerate(state.selected_products, start=1):
                        items.append({"product_id": f"item-{index}", "name": name, "quantity": 1})
                result = self.executor.execute(
                    tenant_id=state.company_id,
                    tool="create_order_draft",
                    channel=state.channel,
                    user_id=state.user_id,
                    arguments={
                        "items": items,
                        "session_id": state.session_id,
                        "payment_preference": state.payment_preference,
                        "invoice_type": state.invoice_type,
                        "invoice_address": state.invoice_address,
                        "delivery_address": state.delivery_address,
                        "pickup_location_label": state.pickup_location_label,
                    },
                )
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                checkout_info = data.get("checkout") if isinstance(data.get("checkout"), dict) else {}
                draft_ok = bool(isinstance(result, dict) and result.get("ok")) and data.get("ok") is not False and str(
                    result.get("code") or ""
                ).strip().lower() not in {"tool_failed", "error"}
                if not draft_ok:
                    # ClubHx no pudo crear el borrador: no prometer nada, dejar el pedido armado y derivar.
                    detail = str(result.get("message") or data.get("message") or "").strip()
                    logger.warning(
                        "commerce_order_draft_failed session_id=%s code=%s detail=%s",
                        state.session_id,
                        result.get("code") if isinstance(result, dict) else None,
                        detail,
                    )
                    return {
                        "answer": (
                            "No pude registrar el pedido en este momento. Ya quedo armado con tus productos, "
                            "medio de pago y datos; una persona del equipo lo va a revisar y te confirma por este mismo chat."
                        ),
                        "intent_label": "order_failed",
                        "workflow_stage": "payment_selection",
                        "checkout_stage": "order_summary_pending",
                        "pending_next_step": "order_confirmation",
                        "workflow_action": {"type": "human_handoff", "payload": {"reason": "order_draft_failed", "detail": detail[:200]}},
                    }
                merged = {**checkout_info, **data}
                answer = _completed_answer(state, merged)
                payload: dict[str, Any] = {
                    "answer": answer,
                    "intent_label": "order_created",
                    "workflow_stage": "browsing",
                    "checkout_stage": "completed",
                    "pending_next_step": "",
                    "awaiting_slot": "",
                    "reset_workflow": True,
                }
                payment_url = str((merged.get("payment_url") or merged.get("payment_link") or merged.get("checkout_url") or merged.get("init_point") or merged.get("url") or "")).strip()
                if payment_url:
                    payload["redirect_to"] = payment_url
                return payload
            return {
                "answer": _order_summary_answer(state),
                "intent_label": "order_summary_confirmation",
                "workflow_stage": "payment_selection",
                "checkout_stage": "order_summary_pending",
                "pending_next_step": "order_confirmation",
            }

        return None
