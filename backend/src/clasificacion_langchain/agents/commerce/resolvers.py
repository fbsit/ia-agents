from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from clasificacion_langchain.chat.session_store import SessionSummary, StoredSessionSummary
from clasificacion_langchain.agents.commerce.extractors import (
    canonical_tool_succeeded,
    extract_address,
    extract_pickup_location,
    is_address_confirmation,
    is_address_correction,
    is_affirmative_followup_message,
    is_email_message,
    is_login_confirmed_message,
    is_whatsapp_reminder_channel,
    match_saved_address_choice,
    parse_iso_datetime,
    product_lookup_queries_from_message,
    saved_addresses_from_workflow_state,
    saved_addresses_prompt,
    split_memory_session_id,
    wants_delivery,
    wants_pickup,
    workflow_action,
    workflow_state_bool,
    workflow_state_customer_authenticated,
)
from clasificacion_langchain.agents.commerce.intent_parser import extract_invoice_data
from clasificacion_langchain.agents.commerce.recent_products import normalize_text as normalize_widget_text
from clasificacion_langchain.agents.commerce.response_mapper import (
    build_payment_options_answer,
    option_names_from_result,
    pickup_option_names_from_result,
)
from clasificacion_langchain.agents.commerce.resume_timeout import (
    resolve_greeting_workflow_followup as _resolve_greeting_followup,
    resolve_legacy_preflight,
    resolve_workflow_resume_followup as _resolve_workflow_resume,
    timeout_message as workflow_timeout_message,
)
from clasificacion_langchain.agents.commerce.widget_payload import (
    payload_awaiting_slot,
    payload_cart_actions,
    payload_focused_product,
    payload_product_names,
    payload_saved_addresses,
)
from clasificacion_langchain.api.support.widget import get_clubhx_tools_client


logger = logging.getLogger(__name__)

WORKFLOW_EXPIRATION_SECONDS = 300
WORKFLOW_RESET_CONFIRMATION_SECONDS = 180


def _trace_route(event: str, **payload: Any) -> None:
    safe_payload = {key: value for key, value in payload.items()}
    print(f"[TRACE_ROUTE] {event} {json.dumps(safe_payload, ensure_ascii=False, default=str)}", flush=True)


def summary_has_active_workflow(summary: SessionSummary) -> bool:
    return any(
        str(value or "").strip()
        for value in [
            summary.funnel_stage,
            summary.checkout_stage,
            summary.pending_next_step,
            summary.awaiting_slot,
            summary.selected_products,
            summary.focused_product,
            summary.shipping_preference,
            summary.pickup_location_label,
            summary.delivery_address,
            summary.invoice_type,
            summary.payment_preference,
            summary.otp_email,
        ]
    ) or bool(summary.customer_authenticated)


def update_agent_memory_from_payload(
    *,
    agent_id: str,
    company_id: str,
    session_id: str,
    user_message: str,
    answer: str,
    payload: dict[str, Any] | None,
    fallback_intent: str | None = None,
    fallback_tool: str | None = None,
    channel: str | None = None,
    reminder_recipient: str | None = None,
    agent_service: Any | None = None,
) -> None:
    if agent_service is None or not session_id:
        return
    intent_label = ""
    if isinstance(payload, dict):
        intent_label = str(payload.get("intent_label") or fallback_intent or "").strip()
    tool_name = fallback_tool or ""
    product_queries = product_lookup_queries_from_message(user_message)
    selected_products = payload_product_names(payload)
    focused_product = payload_focused_product(payload)
    awaiting_slot = payload_awaiting_slot(payload)
    cart_actions = payload_cart_actions(payload)
    cart_products = [product for product in ((payload or {}).get("products") if isinstance((payload or {}).get("products"), list) else []) if isinstance(product, dict)]
    saved_addresses = payload_saved_addresses(payload)
    shipping_preference = user_message if any(token in normalize_widget_text(user_message) for token in ["envio", "despacho", "retiro", "comuna"]) else None
    payment_preference = user_message if any(token in normalize_widget_text(user_message) for token in ["pago", "tarjeta", "transferencia", "link de pago"]) else None
    pickup_location_label = extract_pickup_location(user_message) or None
    delivery_address = extract_address(user_message) or None
    delivery_address_confirmed = True if isinstance(payload, dict) and str(payload.get("intent_label") or "").strip() == "delivery_address_confirmed" else None
    invoice_data = extract_invoice_data(user_message, session_id=session_id)
    invoice_type = invoice_data.get("invoice_type")
    invoice_rut = invoice_data.get("rut")
    invoice_business_name = invoice_data.get("business_name")
    invoice_address = invoice_data.get("invoice_address")
    customer_authenticated = True if is_login_confirmed_message(user_message) else None
    if customer_authenticated is None and isinstance(payload, dict):
        intent = str(payload.get("intent_label") or "").strip()
        if intent in {"checkout_auth_confirmed", "checkout_otp_sent", "checkout_otp_invalid"}:
            customer_authenticated = intent == "checkout_auth_confirmed"
    payload_workflow_stage = str((payload or {}).get("workflow_stage") or "").strip()
    payload_pending_next_step = str((payload or {}).get("pending_next_step") or "").strip()
    payload_checkout_stage = str((payload or {}).get("checkout_stage") or "").strip()

    try:
        _trace_route(
            "memory.update_request",
            agent_id=agent_id,
            company_id=company_id,
            session_id=session_id,
            intent_label=intent_label,
            workflow_stage=payload_workflow_stage,
            checkout_stage=payload_checkout_stage,
            pending_next_step=payload_pending_next_step,
            awaiting_slot=awaiting_slot or "",
            selected_products=selected_products,
            focused_product=focused_product or "",
            shipping_preference=shipping_preference or "",
            payment_preference=payment_preference or "",
            invoice_type=invoice_type or "",
            invoice_address=invoice_address or "",
            saved_addresses=saved_addresses or "",
        )
        agent_service.update_session_summary(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
            user_message=user_message,
            assistant_message=answer,
            intent_label=intent_label or None,
            tool_name=tool_name or None,
            product_queries=product_queries,
            selected_products=selected_products,
            shipping_preference=shipping_preference,
            pickup_location_label=pickup_location_label,
            delivery_address=delivery_address,
            delivery_address_confirmed=delivery_address_confirmed,
            invoice_type=invoice_type,
            invoice_rut=invoice_rut,
            invoice_business_name=invoice_business_name,
            invoice_address=invoice_address,
            payment_preference=payment_preference,
            saved_addresses=saved_addresses,
            customer_authenticated=customer_authenticated,
            order_reference=None,
            workflow_stage=payload_workflow_stage or None,
            pending_next_step=payload_pending_next_step or None,
            awaiting_slot=awaiting_slot,
            checkout_stage=payload_checkout_stage or None,
            focused_product=focused_product,
            cart_actions=cart_actions,
            cart_products=cart_products,
            otp_email=str((payload or {}).get("otp_email") or "").strip() or None,
            authenticated_at=str((payload or {}).get("authenticated_at") or "").strip() or None,
            reset_workflow=bool((payload or {}).get("reset_workflow")),
            workflow_timeout_sent_at="" if bool((payload or {}).get("reset_workflow")) else None,
            channel=channel,
            reminder_recipient=reminder_recipient,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent_summary_update_failed agent_id=%s company_id=%s session_id=%s detail=%s",
            agent_id,
            company_id,
            session_id,
            exc,
        )


def fetch_saved_addresses_for_user(
    *,
    clubhx_tools_client: Any | None,
    company_id: str | None,
    user_id: str | None,
    channel: str | None,
) -> list[dict[str, str]]:
    if clubhx_tools_client is None or not user_id:
        return []
    try:
        result = clubhx_tools_client.execute_canonical(
            tenant_id=company_id or "",
            tool="get_addresses",
            channel=channel or "",
            user_id=user_id,
            arguments={},
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("saved_addresses_unavailable user_id=%s detail=%s", user_id, exc)
        return []
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    rows = data.get("items") if isinstance(data.get("items"), list) else data.get("addresses") if isinstance(data.get("addresses"), list) else []
    addresses: list[dict[str, str]] = []
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or f"Direccion {index}").strip() or f"Direccion {index}"
        street = str(item.get("street") or item.get("address") or item.get("full_address") or "").strip()
        city = str(item.get("city") or item.get("commune") or "").strip()
        address = ", ".join(part for part in [street, city] if part)
        if not address:
            continue
        addresses.append({"label": label, "address": address})
    return addresses


def create_address_for_user(
    clubhx_tools_client: Any | None,
    company_id: str | None,
    user_id: str | None,
    address_text: str,
    channel: str | None = None,
) -> None:
    if clubhx_tools_client is None or not user_id or not address_text:
        return
    parts = [p.strip() for p in address_text.split(",")]
    street = parts[0] if parts else address_text
    city = parts[1] if len(parts) > 1 else ""
    number = ""
    for segment in street.split():
        if any(c.isdigit() for c in segment) and not number:
            idx = street.find(segment)
            number = segment
            street = street[:idx].strip()
            break
    try:
        clubhx_tools_client.execute_canonical(
            tenant_id=company_id or "",
            tool="create_address",
            channel=channel or "",
            user_id=user_id,
            arguments={
                "name": "Dirección de despacho",
                "street": street,
                "number": number,
                "city": city,
            },
        )
        logger.info("create_address_ok user_id=%s street=%s number=%s city=%s", user_id, street, number, city)
    except Exception as exc:
        logger.warning("create_address_failed user_id=%s address=%s detail=%s", user_id, address_text, exc)


def process_workflow_reminders_once(
    *,
    agent_service: Any | None = None,
) -> None:
    if agent_service is None:
        return
    session_store = getattr(agent_service, "session_store", None)
    if session_store is None or not hasattr(session_store, "list_summaries"):
        return
    client = get_clubhx_tools_client()
    if client is None:
        return

    now = datetime.now(UTC)
    for stored in session_store.list_summaries():
        if not isinstance(stored, StoredSessionSummary):
            continue
        summary = stored.summary
        if not summary_has_active_workflow(summary):
            continue
        if not is_whatsapp_reminder_channel(summary.last_channel):
            continue
        recipient = str(summary.reminder_recipient or "").strip()
        if not recipient:
            continue

        session_parts = split_memory_session_id(stored.session_id)
        if session_parts is None:
            continue
        agent_id, plain_session_id = session_parts

        updated_at = parse_iso_datetime(summary.updated_at)
        if updated_at is None:
            continue
        reset_started_at = parse_iso_datetime(summary.workflow_reset_started_at)
        inactivity_seconds = (now - updated_at).total_seconds()

        if reset_started_at is None:
            if inactivity_seconds <= WORKFLOW_EXPIRATION_SECONDS:
                continue
            if summary.workflow_timeout_sent_at:
                continue
            try:
                client.send_whatsapp_message(
                    tenant_id=stored.company_id,
                    to=recipient,
                    message=workflow_timeout_message(),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "workflow_timeout_send_failed company_id=%s agent_id=%s session_id=%s recipient=%s detail=%s",
                    stored.company_id,
                    agent_id,
                    plain_session_id,
                    recipient,
                    exc,
                )
                continue
            sent_at = now.isoformat()
            agent_service.update_session_summary(
                company_id=stored.company_id,
                agent_id=agent_id,
                session_id=plain_session_id,
                workflow_reset_started_at=sent_at,
                workflow_timeout_sent_at=sent_at,
                channel=summary.last_channel,
                reminder_recipient=recipient,
            )
            logger.info(
                "workflow_timeout_sent company_id=%s agent_id=%s session_id=%s recipient=%s",
                stored.company_id,
                agent_id,
                plain_session_id,
                recipient,
            )
            continue

        if (now - reset_started_at).total_seconds() <= WORKFLOW_RESET_CONFIRMATION_SECONDS:
            continue
        agent_service.update_session_summary(
            company_id=stored.company_id,
            agent_id=agent_id,
            session_id=plain_session_id,
            reset_workflow=True,
            workflow_timeout_sent_at="",
            channel=summary.last_channel,
            reminder_recipient=recipient,
        )
        logger.info(
            "workflow_timeout_reset company_id=%s agent_id=%s session_id=%s",
            stored.company_id,
            agent_id,
            plain_session_id,
        )


def resolve_affirmative_workflow_followup(
    *,
    message: str,
    workflow_state: dict[str, str] | None,
) -> dict[str, Any] | None:
    if not is_affirmative_followup_message(message):
        return None
    next_step = str((workflow_state or {}).get("pending_next_step") or "").strip().lower()
    stage = str((workflow_state or {}).get("stage") or "").strip().lower()
    effective_next = next_step or ("shipping_selection" if stage == "cart_building" else stage)
    if effective_next in {"shipping_selection", "shipping"}:
        return {
            "answer": "Perfecto. Para seguir con el despacho, dime tu comuna o si prefieres retiro en tienda.",
            "intent_label": "shipping_options",
            "workflow_stage": "shipping_selection",
            "pending_next_step": "shipping_selection",
            "checkout_stage": "shipping_method_pending",
            "workflow_action": workflow_action("choose_shipping_method"),
        }
    if effective_next in {"payment_selection", "payment"}:
        return {
            "answer": "Perfecto. Para seguir con el pago, te puedo mostrar medios disponibles o generar el siguiente paso si ya tienes el carrito listo.",
            "intent_label": "payment_options",
            "workflow_stage": "payment_selection",
            "pending_next_step": "payment_selection",
            "checkout_stage": "payment_method_pending",
            "workflow_action": workflow_action("choose_payment_method"),
        }
    if effective_next in {"order_confirmation", "checkout_confirmation", "review_order"}:
        return None
    return None


def resolve_greeting_workflow_followup(
    *,
    message: str,
    workflow_state: dict[str, str] | None,
    is_greeting_message: Any = None,
) -> dict[str, Any] | None:
    if is_greeting_message is None:
        # Import diferido: helpers no depende de resolvers, pero mantenemos el acople minimo.
        from clasificacion_langchain.agents.commerce.helpers import is_likely_greeting_message

        is_greeting_message = is_likely_greeting_message
    payload = _resolve_greeting_followup(
        message=message,
        workflow_state=workflow_state,
        is_greeting_message=is_greeting_message,
    )
    return dict(payload) if isinstance(payload, dict) else None


def resolve_workflow_resume_followup(workflow_state: dict[str, str] | None) -> dict[str, Any] | None:
    payload = _resolve_workflow_resume(workflow_state)
    return dict(payload) if isinstance(payload, dict) else None


def legacy_checkout_preflight_response(
    *,
    company_id: str,
    agent_id: str | None,
    session_id: str,
    message: str,
    channel: str,
    workflow_state: dict[str, str] | None,
    agent_service: Any | None = None,
) -> dict[str, Any] | None:
    def _clear_timeout_markers() -> None:
        if agent_service is not None and agent_id:
            agent_service.update_session_summary(
                company_id=company_id,
                agent_id=agent_id,
                session_id=session_id,
                workflow_reset_started_at="",
                workflow_timeout_sent_at="",
            )

    resolution = resolve_legacy_preflight(
        message=message,
        workflow_state=workflow_state,
        clear_timeout_markers=_clear_timeout_markers,
        is_affirmative_message=is_affirmative_followup_message,
    )
    if not resolution.handled:
        return None
    payload = dict(resolution.payload) if isinstance(resolution.payload, dict) else None
    if payload and str(payload.get("intent_label") or "") == "workflow_reset":
        _trace_route("commerce.workflow_expired", session_id=session_id, channel=channel, message=message)
        logger.info("commerce_router_workflow_expired session_id=%s channel=%s message=%s", session_id, channel, message)
    if payload and str(payload.get("answer") or "") == workflow_timeout_message():
        logger.info("commerce_router_timeout_confirmation session_id=%s channel=%s", session_id, channel)
    if payload and str(payload.get("answer") or "").startswith("Perfecto, retomamos tu pedido"):
        _trace_route(
            "commerce.workflow_resumed",
            session_id=session_id,
            channel=channel,
            checkout_stage=str(payload.get("checkout_stage") or ""),
            pending_next_step=str(payload.get("pending_next_step") or ""),
        )
    return payload


def resolve_checkout_workflow_followup(
    *,
    message: str,
    session_id: str | None = None,
    workflow_state: dict[str, str] | None,
    company_id: str | None = None,
    channel: str | None = None,
    user_id: str | None = None,
    clubhx_tools_client: Any | None = None,
) -> dict[str, Any] | None:
    current_checkout_stage = str((workflow_state or {}).get("checkout_stage") or "").strip()
    current_pending_next_step = str((workflow_state or {}).get("pending_next_step") or "").strip().lower()
    current_customer_authenticated = workflow_state_customer_authenticated(workflow_state)
    current_otp_email = str((workflow_state or {}).get("otp_email") or "").strip()
    logger.warning(
        "checkout_followup_state session_id=%s checkout_stage=%s pending_next_step=%s authenticated=%s message=%s otp_email=%s",
        session_id,
        current_checkout_stage,
        current_pending_next_step,
        current_customer_authenticated,
        message,
        current_otp_email,
    )
    logger.info(
        "checkout_followup_entry session_id=%s stage=%s pending_next_step=%s otp_email=%s message=%s",
        session_id,
        current_checkout_stage,
        current_pending_next_step,
        current_otp_email,
        message,
    )
    _trace_route(
        "checkout_followup.check_stage",
        session_id=session_id,
        current_stage=current_checkout_stage,
        pending_next_step=current_pending_next_step,
        is_email=is_email_message(message),
    )

    if not current_customer_authenticated and current_pending_next_step in {"auth_confirmation", "auth_pending"} and is_email_message(message):
        logger.info(
            "checkout_followup_send_otp_attempt session_id=%s email=%s stage=%s pending_next_step=%s",
            session_id,
            message.strip(),
            current_checkout_stage,
            current_pending_next_step,
        )
        send_ok = False
        if clubhx_tools_client is not None:
            try:
                result = clubhx_tools_client.execute_canonical(
                    tenant_id=company_id or "",
                    tool="send_verification_code",
                    channel=channel or "",
                    user_id=user_id,
                    arguments={"email": message.strip()},
                )
                logger.info(
                    "checkout_followup_send_otp_result session_id=%s email=%s result=%s",
                    session_id,
                    message.strip(),
                    result,
                )
                send_ok = canonical_tool_succeeded(result, expected_statuses={"sent", "ok", "success"})
            except Exception as exc:
                logger.warning(
                    "checkout_followup_send_otp_failed session_id=%s email=%s detail=%s",
                    session_id,
                    message.strip(),
                    exc,
                )
        if not send_ok:
            logger.warning(
                "checkout_followup_send_otp_not_ok session_id=%s email=%s stage=%s pending_next_step=%s",
                session_id,
                message.strip(),
                current_checkout_stage,
                current_pending_next_step,
            )
            return {
                "answer": "No pude enviar el código de verificación. Probá de nuevo o avisame si querés reintentar con otro correo.",
                "intent_label": "checkout_otp_send_failed",
                "workflow_stage": "checkout_ready",
                "checkout_stage": "auth_pending",
                "pending_next_step": "auth_confirmation",
                "workflow_action": workflow_action("otp_send_failed"),
            }
        return {
            "answer": f"Te enviamos un codigo de verificacion a {message.strip()}. Ingresalo aca para continuar.",
            "intent_label": "checkout_otp_sent",
            "workflow_stage": "checkout_ready",
            "checkout_stage": "otp_pending",
            "pending_next_step": "otp_verification",
            "otp_email": message.strip(),
            "workflow_action": workflow_action("otp_sent"),
        }

    if current_pending_next_step == "otp_verification" or current_checkout_stage == "otp_pending":
        otp_email = str((workflow_state or {}).get("otp_email") or "").strip()
        logger.info(
            "checkout_followup_verify_otp_attempt session_id=%s message=%s stage=%s pending_next_step=%s otp_email=%s",
            session_id,
            message.strip(),
            current_checkout_stage,
            current_pending_next_step,
            otp_email,
        )
        otp_ok = False
        if clubhx_tools_client is not None and otp_email:
            try:
                result = clubhx_tools_client.execute_canonical(
                    tenant_id=company_id or "",
                    tool="verify_verification_code",
                    channel=channel or "",
                    user_id=user_id,
                    arguments={"email": otp_email, "code": message.strip()},
                )
                logger.info(
                    "checkout_followup_verify_otp_result session_id=%s code=%s otp_email=%s result=%s",
                    session_id,
                    message.strip(),
                    otp_email,
                    result,
                )
                if canonical_tool_succeeded(result, expected_statuses={"verified", "valid", "ok", "success"}):
                    otp_ok = True
            except Exception as exc:
                logger.warning(
                    "checkout_followup_verify_otp_failed session_id=%s code=%s otp_email=%s detail=%s",
                    session_id,
                    message.strip(),
                    otp_email,
                    exc,
                )
        if not otp_ok:
            logger.warning(
                "checkout_followup_verify_otp_not_ok session_id=%s code=%s stage=%s pending_next_step=%s otp_email=%s",
                session_id,
                message.strip(),
                current_checkout_stage,
                current_pending_next_step,
                otp_email,
            )
            return {
                "answer": "El codigo ingresado no es valido. Intenta de nuevo o escribe tu correo para reenviar el codigo.",
                "intent_label": "checkout_otp_invalid",
                "workflow_stage": "checkout_ready",
                "checkout_stage": "otp_pending",
                "pending_next_step": "otp_verification",
                "workflow_action": workflow_action("otp_invalid"),
            }
        return {
            "answer": "Perfecto, ya estas autenticado. Ahora dime si prefieres retiro en tienda o despacho.",
            "intent_label": "checkout_auth_confirmed",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "shipping_method_pending",
            "pending_next_step": "shipping_selection",
            "authenticated_at": datetime.now(UTC).isoformat(),
            "workflow_action": workflow_action("auth_confirmed", authenticated=True),
        }

    if is_login_confirmed_message(message):
        return {
            "answer": "Perfecto, tomo que ya iniciaste sesion. Ahora dime si prefieres retiro en tienda o despacho.",
            "intent_label": "checkout_auth_confirmed",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "shipping_method_pending",
            "pending_next_step": "shipping_selection",
            "authenticated_at": datetime.now(UTC).isoformat(),
            "workflow_action": workflow_action("auth_confirmed", authenticated=True),
        }

    pickup_location = extract_pickup_location(message)
    if pickup_location:
        payment_names: list[str] = []
        if clubhx_tools_client is not None:
            try:
                payment_result = clubhx_tools_client.execute_canonical(
                    tenant_id=company_id or "",
                    tool="get_payment_options",
                    channel=channel or "",
                    user_id=user_id,
                    arguments={"session_id": session_id or ""},
                )
                payment_names = option_names_from_result(payment_result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("pickup_payment_options_failed session_id=%s detail=%s", session_id, exc)
        return {
            "answer": (
                f"Perfecto, dejo retiro en {pickup_location}. {build_payment_options_answer(payment_names)}"
                if payment_names
                else f"Perfecto, dejo retiro en {pickup_location}. Ahora dime que medio de pago prefieres."
            ),
            "intent_label": "pickup_location_selected",
            "workflow_stage": "payment_selection",
            "checkout_stage": "pickup_location_selected",
            "pending_next_step": "payment_selection",
            "awaiting_slot": "payment_method",
            "workflow_action": workflow_action(
                "pickup_location_selected",
                pickup_location_label=pickup_location,
            ),
        }

    if wants_pickup(message):
        pickup_names: list[str] = []
        payment_names: list[str] = []
        if clubhx_tools_client is not None:
            try:
                shipping_result = clubhx_tools_client.execute_canonical(
                    tenant_id=company_id or "",
                    tool="get_shipping_options",
                    channel=channel or "",
                    user_id=user_id,
                    arguments={"session_id": session_id or ""},
                )
                pickup_names = pickup_option_names_from_result(shipping_result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("pickup_shipping_options_failed session_id=%s detail=%s", session_id, exc)
            try:
                payment_result = clubhx_tools_client.execute_canonical(
                    tenant_id=company_id or "",
                    tool="get_payment_options",
                    channel=channel or "",
                    user_id=user_id,
                    arguments={"session_id": session_id or ""},
                )
                payment_names = option_names_from_result(payment_result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("pickup_payment_options_failed session_id=%s detail=%s", session_id, exc)
        if not pickup_names:
            return {
                "answer": (
                    f"Perfecto, dejo retiro en tienda. {build_payment_options_answer(payment_names)}"
                    if payment_names
                    else "Perfecto, dejo retiro en tienda. Ahora dime que medio de pago prefieres."
                ),
                "intent_label": "pickup_selected",
                "workflow_stage": "payment_selection",
                "checkout_stage": "pickup_location_selected",
                "pending_next_step": "payment_selection",
                "awaiting_slot": "payment_method",
                "workflow_action": workflow_action("pickup_location_selected", pickup_location_label="retiro en tienda"),
            }
        return {
            "answer": (
                f"Perfecto, podemos seguir con retiro. Opciones disponibles: {', '.join(pickup_names)}. Cual prefieres?"
                if pickup_names
                else "Perfecto, podemos seguir con retiro. Dime en que tienda o punto de retiro quieres retirar."
            ),
            "intent_label": "pickup_selected",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "pickup_location_pending",
            "pending_next_step": "shipping_selection",
            "workflow_action": workflow_action("choose_pickup_location"),
        }

    existing_address = str((workflow_state or {}).get("delivery_address") or "").strip()
    address_confirmed = workflow_state_bool((workflow_state or {}).get("delivery_address_confirmed"))

    if existing_address and is_address_confirmation(message):
        create_address_for_user(
            clubhx_tools_client=clubhx_tools_client,
            company_id=company_id,
            user_id=user_id,
            address_text=existing_address,
            channel=channel,
        )
        return {
            "answer": f"Perfecto, confirmo direccion: {existing_address}. Ahora pasemos al pago.",
            "intent_label": "delivery_address_confirmed",
            "workflow_stage": "payment_selection",
            "checkout_stage": "delivery_address_confirmed",
            "pending_next_step": "payment_selection",
            "workflow_action": workflow_action(
                "delivery_address_confirmed",
                delivery_address=existing_address,
            ),
        }

    if existing_address and is_address_correction(message):
        return {
            "answer": "Dime la direccion correcta para el despacho.",
            "intent_label": "delivery_address_correction",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "delivery_address_pending",
            "pending_next_step": "delivery_address",
            "workflow_action": workflow_action("delivery_address_correction"),
        }

    address = extract_address(message)
    fiscal_checkout_stage = current_checkout_stage.lower() in {"document_type_pending", "invoice_data_pending", "invoice_address_pending"}
    if address and not fiscal_checkout_stage:
        return {
            "answer": f"Encontre esta direccion de despacho:\n{address}\n\nEsta correcta?",
            "intent_label": "delivery_address_proposed",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "delivery_address_proposed",
            "pending_next_step": "delivery_address_confirmation",
            "workflow_action": workflow_action(
                "delivery_address_proposed",
                delivery_address=address,
            ),
        }

    if wants_delivery(message):
        return {
            "answer": "Perfecto, dime la direccion donde quieres recibir el pedido (calle, numero, comuna).",
            "intent_label": "delivery_selected",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "delivery_address_pending",
            "pending_next_step": "delivery_address",
            "workflow_action": workflow_action("choose_delivery_address"),
        }

    past_shipping = current_checkout_stage in {
        "delivery_address_confirmed",
        "pickup_location_selected",
        "delivery_address_proposed",
        "delivery_address_confirmation",
        "document_type_pending",
        "payment_method_pending",
    }
    current_invoice_type = str((workflow_state or {}).get("invoice_type") or "").strip().lower()
    current_rut = str((workflow_state or {}).get("invoice_rut") or "").strip()
    current_business_name = str((workflow_state or {}).get("invoice_business_name") or "").strip()
    current_invoice_address = str((workflow_state or {}).get("invoice_address") or "").strip()

    document_type_pending_state = current_checkout_stage == "document_type_pending" or current_pending_next_step == "document_type"

    if document_type_pending_state and current_invoice_type == "boleta":
        _trace_route(
            "checkout_followup.document_type_resolved",
            session_id=session_id,
            document_type="boleta",
            source="workflow_state",
            next_checkout_stage="order_summary_pending",
        )
        return {
            "answer": "Perfecto, se emite boleta. Si esta correcto, confirmamelo y te genero el siguiente paso.",
            "intent_label": "invoice_summary_ready",
            "workflow_stage": "payment_selection",
            "checkout_stage": "order_summary_pending",
            "pending_next_step": "order_confirmation",
            "workflow_action": workflow_action("invoice_summary_ready", invoice_type="boleta"),
        }

    if document_type_pending_state and current_invoice_type == "factura":
        delivery_addr = str((workflow_state or {}).get("delivery_address") or "").strip()
        saved_addresses = fetch_saved_addresses_for_user(
            clubhx_tools_client=clubhx_tools_client,
            company_id=company_id,
            user_id=user_id,
            channel=channel,
        )
        _trace_route(
            "checkout_followup.document_type_resolved",
            session_id=session_id,
            document_type="factura",
            source="workflow_state",
            saved_addresses_count=len(saved_addresses),
            has_delivery_address=bool(delivery_addr),
            next_checkout_stage="invoice_address_pending",
        )
        if saved_addresses:
            return {
                "answer": saved_addresses_prompt(saved_addresses),
                "intent_label": "invoice_address_pending",
                "workflow_stage": "payment_selection",
                "checkout_stage": "invoice_address_pending",
                "pending_next_step": "invoice_address",
                "saved_addresses": saved_addresses,
                "workflow_action": workflow_action("request_invoice_address"),
            }
        if delivery_addr:
            return {
                "answer": f"La direccion de facturacion es la misma de despacho?\n{delivery_addr}",
                "intent_label": "invoice_address_pending",
                "workflow_stage": "payment_selection",
                "checkout_stage": "invoice_address_pending",
                "pending_next_step": "invoice_address",
                "workflow_action": workflow_action("request_invoice_address", delivery_address=delivery_addr),
            }
        return {
            "answer": "Dime la direccion de facturacion (calle, numero, comuna).",
            "intent_label": "invoice_address_pending",
            "workflow_stage": "payment_selection",
            "checkout_stage": "invoice_address_pending",
            "pending_next_step": "invoice_address",
            "workflow_action": workflow_action("request_invoice_address"),
        }

    if past_shipping and not current_invoice_type:
        invoice_data = extract_invoice_data(message, session_id=session_id)
        factura_match = invoice_data.get("invoice_type") == "factura"
        boleta_match = invoice_data.get("invoice_type") == "boleta"
        _trace_route(
            "checkout_followup.document_type_eval",
            session_id=session_id,
            checkout_stage=current_checkout_stage,
            pending_next_step=current_pending_next_step,
            current_invoice_type=current_invoice_type,
            extracted_invoice_type=str(invoice_data.get("invoice_type") or ""),
            factura_match=factura_match,
            boleta_match=boleta_match,
        )
        if factura_match:
            invoice_addr = invoice_data.get("invoice_address") or current_invoice_address
            delivery_addr = str((workflow_state or {}).get("delivery_address") or "").strip()
            saved_addresses = fetch_saved_addresses_for_user(
                clubhx_tools_client=clubhx_tools_client,
                company_id=company_id,
                user_id=user_id,
                channel=channel,
            )
            if saved_addresses:
                return {
                    "answer": saved_addresses_prompt(saved_addresses),
                    "intent_label": "invoice_address_pending",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "invoice_address_pending",
                    "pending_next_step": "invoice_address",
                    "saved_addresses": saved_addresses,
                    "workflow_action": workflow_action("request_invoice_address"),
                }
            if not invoice_addr and delivery_addr:
                return {
                    "answer": f"La direccion de facturacion es la misma de despacho?\n{delivery_addr}",
                    "intent_label": "invoice_address_pending",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "invoice_address_pending",
                    "pending_next_step": "invoice_address",
                    "workflow_action": workflow_action(
                        "request_invoice_address",
                        delivery_address=delivery_addr,
                    ),
                }
            if not invoice_addr:
                return {
                    "answer": "Dime la direccion de facturacion (calle, numero, comuna).",
                    "intent_label": "invoice_address_pending",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "invoice_address_pending",
                    "pending_next_step": "invoice_address",
                    "workflow_action": workflow_action("request_invoice_address"),
                }
            return {
                "answer": (
                    f"Perfecto, usare direccion de factura: {invoice_addr}.\n"
                    "Si esta correcto, confirmamelo y te genero el siguiente paso."
                ),
                "intent_label": "invoice_summary_ready",
                "workflow_stage": "payment_selection",
                "checkout_stage": "order_summary_pending",
                "pending_next_step": "order_confirmation",
                "workflow_action": workflow_action(
                    "invoice_summary_ready",
                    invoice_type="factura",
                    invoice_address=invoice_addr,
                ),
            }
        if boleta_match:
            _trace_route(
                "checkout_followup.document_type_resolved",
                session_id=session_id,
                document_type="boleta",
                next_checkout_stage="order_summary_pending",
            )
            return {
                "answer": "Perfecto, se emite boleta. Si esta correcto, confirmamelo y te genero el siguiente paso.",
                "intent_label": "invoice_summary_ready",
                "workflow_stage": "payment_selection",
                "checkout_stage": "order_summary_pending",
                "pending_next_step": "order_confirmation",
                "workflow_action": workflow_action("invoice_summary_ready", invoice_type="boleta"),
            }

    if current_invoice_type == "factura" and current_checkout_stage in {"invoice_data_pending", "delivery_address_confirmed", "pickup_location_selected"}:
        invoice_data = extract_invoice_data(message, session_id=session_id)
        invoice_addr = invoice_data.get("invoice_address") or current_invoice_address
        delivery_addr = str((workflow_state or {}).get("delivery_address") or "").strip()
        has_new_data = bool(invoice_addr)
        _trace_route(
            "checkout_followup.factura_address_eval",
            session_id=session_id,
            checkout_stage=current_checkout_stage,
            pending_next_step=current_pending_next_step,
            invoice_addr=str(invoice_addr or ""),
            has_new_data=has_new_data,
            saved_addresses_count=len(saved_addresses_from_workflow_state(workflow_state)),
            has_delivery_address=bool(delivery_addr),
        )
        if has_new_data:
            saved_addresses = fetch_saved_addresses_for_user(
                clubhx_tools_client=clubhx_tools_client,
                company_id=company_id,
                user_id=user_id,
                channel=channel,
            )
            if saved_addresses:
                return {
                    "answer": saved_addresses_prompt(saved_addresses),
                    "intent_label": "invoice_address_pending",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "invoice_address_pending",
                    "pending_next_step": "invoice_address",
                    "saved_addresses": saved_addresses,
                    "workflow_action": workflow_action("request_invoice_address"),
                }
            if not invoice_addr and delivery_addr:
                return {
                    "answer": f"La direccion de facturacion es la misma de despacho?\n{delivery_addr}",
                    "intent_label": "invoice_address_pending",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "invoice_address_pending",
                    "pending_next_step": "invoice_address",
                    "workflow_action": workflow_action("request_invoice_address", delivery_address=delivery_addr),
                }
            if not invoice_addr:
                return {"answer": "Dime la direccion de facturacion (calle, numero, comuna)."}
            return {
                "answer": (
                    f"Perfecto, usare direccion de factura: {invoice_addr}.\n"
                    "Si esta correcto, confirmamelo y te genero el siguiente paso."
                ),
                "intent_label": "invoice_summary_ready",
                "workflow_stage": "payment_selection",
                "checkout_stage": "order_summary_pending",
                "pending_next_step": "order_confirmation",
                "workflow_action": workflow_action(
                    "invoice_summary_ready", invoice_type="factura", invoice_address=invoice_addr,
                ),
            }

    if current_checkout_stage == "invoice_address_pending":
        delivery_addr = str((workflow_state or {}).get("delivery_address") or "").strip()
        saved_addresses = saved_addresses_from_workflow_state(workflow_state)
        selected_saved_address = match_saved_address_choice(message, saved_addresses)
        _trace_route(
            "checkout_followup.invoice_address_pending_eval",
            session_id=session_id,
            saved_addresses_count=len(saved_addresses),
            selected_saved_address=selected_saved_address,
            has_delivery_address=bool(delivery_addr),
            is_address_confirmation=is_address_confirmation(message),
            wants_delivery=wants_delivery(message),
        )
        if selected_saved_address:
            return {
                "answer": (
                    f"Direccion de facturacion: {selected_saved_address}.\n"
                    "Si esta correcto, confirmamelo y te genero el siguiente paso."
                ),
                "intent_label": "invoice_address_confirmed",
                "workflow_stage": "payment_selection",
                "checkout_stage": "order_summary_pending",
                "pending_next_step": "order_confirmation",
                "saved_addresses": saved_addresses,
                "workflow_action": workflow_action(
                    "invoice_address_confirmed", invoice_address=selected_saved_address,
                ),
            }
        if is_address_confirmation(message) and delivery_addr:
            return {
                "answer": (
                    f"Perfecto, uso la misma direccion de despacho: {delivery_addr}.\n"
                    "Si esta correcto, confirmamelo y te genero el siguiente paso."
                ),
                "intent_label": "invoice_address_confirmed",
                "workflow_stage": "payment_selection",
                "checkout_stage": "order_summary_pending",
                "pending_next_step": "order_confirmation",
                "workflow_action": workflow_action(
                    "invoice_address_confirmed", invoice_address=delivery_addr,
                ),
            }
        invoice_data = extract_invoice_data(message, session_id=session_id)
        invoice_addr = invoice_data.get("invoice_address") or extract_address(message)
        if invoice_addr:
            return {
                "answer": (
                    f"Direccion de facturacion: {invoice_addr}.\n"
                    "Si esta correcto, confirmamelo y te genero el siguiente paso."
                ),
                "intent_label": "invoice_address_confirmed",
                "workflow_stage": "payment_selection",
                "checkout_stage": "order_summary_pending",
                "pending_next_step": "order_confirmation",
                "workflow_action": workflow_action(
                    "invoice_address_confirmed", invoice_address=invoice_addr,
                ),
            }
        if wants_delivery(message) or any(token in normalize_widget_text(message) for token in ["misma", "igual", "misma direccion"]):
            return {
                "answer": (
                    "Perfecto, uso la direccion de despacho.\n"
                    "Si esta correcto, confirmamelo y te genero el siguiente paso."
                ),
                "intent_label": "invoice_address_confirmed",
                "workflow_stage": "payment_selection",
                "checkout_stage": "order_summary_pending",
                "pending_next_step": "order_confirmation",
                "workflow_action": workflow_action(
                    "invoice_address_confirmed", invoice_address=delivery_addr or "",
                ),
            }

    _trace_route(
        "checkout_followup.no_match",
        session_id=session_id,
        checkout_stage=current_checkout_stage,
        pending_next_step=current_pending_next_step,
        customer_authenticated=current_customer_authenticated,
        has_delivery_address=bool(str((workflow_state or {}).get("delivery_address") or "").strip()),
        invoice_type=current_invoice_type,
    )
    return None
