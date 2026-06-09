from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import queue as stdlib_queue
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import (
    Form,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.chat.config import ChatServiceConfig
from clasificacion_langchain.chat.memory_store import InMemorySessionStore
from clasificacion_langchain.chat.redis_store import RedisSessionStore
from clasificacion_langchain.chat.schemas import ChatRequest
from clasificacion_langchain.chat.service import ChatService
from clasificacion_langchain.auth.schemas import AuthPrincipal
from clasificacion_langchain.auth.service import AuthService
from clasificacion_langchain.auth.token_service import AuthTokenError, TokenService
from clasificacion_langchain.agents.repository import InMemoryAgentRepository
from clasificacion_langchain.agents.postgres_repository import PostgresAgentRepository
from clasificacion_langchain.agents.sqlite_repository import SQLiteAgentRepository
from clasificacion_langchain.agents.service import (
    AgentDocumentNotFoundError,
    AgentForbiddenError,
    AgentNotFoundError,
    AgentService,
    AgentValidationError,
)
from clasificacion_langchain.agents.conversation_policy import (
    build_conversation_policy_from_env,
)
from clasificacion_langchain.agents.commerce_workflow import (
    build_state as build_workflow_state,
    resolve_transition as resolve_workflow_transition,
)
from clasificacion_langchain.agents.role_knowledge import build_role_context
from clasificacion_langchain.persistence.inmemory_identity_store import InMemoryIdentityStore
from clasificacion_langchain.persistence.postgres_identity_store import PostgresIdentityStore
from clasificacion_langchain.persistence.sqlite_identity_store import SQLiteIdentityStore
from clasificacion_langchain.tenancy.service import (
    TenantContextError,
    TenantForbiddenError,
    TenancyService,
)
from clasificacion_langchain.settings.service import (
    InMemoryTenantLlmSettingsStore,
    TenantLlmSettings,
    TenantLlmSettingsService,
)
from clasificacion_langchain.settings.postgres_store import PostgresTenantLlmSettingsStore
from clasificacion_langchain.settings.sqlite_store import SQLiteTenantLlmSettingsStore
from clasificacion_langchain.rag.generation import (
    enforce_channel_response_contract,
    tune_answer_style,
)
from clasificacion_langchain.analytics.chat_audit import (
    ChatAuditCostRow,
    ChatAuditRecord,
    ChatAuditSummaryRow,
    build_chat_audit_service_from_env,
)
from clasificacion_langchain.analytics.retrieval_audit import (
    RetrievalBackendMetrics,
    RetrievalComparisonRow,
    RetrievalAuditRecord,
    RetrievalAuditSummaryRow,
    build_retrieval_audit_service_from_env,
)
from clasificacion_langchain.analytics.feedback_audit import (
    AgentFeedbackRecord,
    AgentFeedbackSummary,
    build_agent_feedback_service_from_env,
)
from clasificacion_langchain.agent_tools import AgentToolset
from clasificacion_langchain.clubhx_tools_client import ClubHxToolsClient


load_dotenv()


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_WIDGET_QUANTITY_WORDS: dict[str, int] = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}

_COMMERCE_CONTEXT_LOCK = threading.Lock()
_COMMERCE_PRODUCT_CONTEXT: dict[str, dict[str, Any]] = {}
_SUPPORTED_COMMERCE_TOOLS = {
    "get_product_availability",
    "get_order_status",
    "get_shipping_options",
    "get_payment_options",
    "create_payment_link",
    "create_order_draft",
}
_GREETING_TERMS = {
    "hola",
    "buenas",
    "buen dia",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "holi",
    "hello",
    "hi",
}


def _normalize_widget_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text or ""))
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = re.sub(r"[^a-zA-Z0-9\s]+", " ", normalized).lower()
    return re.sub(r"\s+", " ", normalized).strip()


def _is_likely_greeting_message(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    return normalized in _GREETING_TERMS


def _trace_route(event: str, **payload: Any) -> None:
    safe_payload = {key: value for key, value in payload.items()}
    print(f"[TRACE_ROUTE] {event} {json.dumps(safe_payload, ensure_ascii=False, default=str)}", flush=True)


def _remember_commerce_products(session_id: str, products: list[dict[str, Any]]) -> None:
    clean_session_id = str(session_id or "").strip()
    if not clean_session_id or not products:
        return
    safe_products = [item for item in products if isinstance(item, dict)][:6]
    if not safe_products:
        return
    with _COMMERCE_CONTEXT_LOCK:
        _COMMERCE_PRODUCT_CONTEXT[clean_session_id] = {
            "products": safe_products,
            "updated_at": time.time(),
        }


def _recent_commerce_products(session_id: str, max_age_seconds: int = 900) -> list[dict[str, Any]]:
    clean_session_id = str(session_id or "").strip()
    if not clean_session_id:
        return []
    with _COMMERCE_CONTEXT_LOCK:
        payload = _COMMERCE_PRODUCT_CONTEXT.get(clean_session_id)
        if not isinstance(payload, dict):
            return []
        updated_at = payload.get("updated_at")
        if not isinstance(updated_at, (int, float)) or time.time() - float(updated_at) > max_age_seconds:
            _COMMERCE_PRODUCT_CONTEXT.pop(clean_session_id, None)
            return []
        products = payload.get("products") if isinstance(payload.get("products"), list) else []
        return [item for item in products if isinstance(item, dict)]


def _is_implicit_add_to_cart_message(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return False
    return any(
        phrase in normalized
        for phrase in [
            "agregalo",
            "agregala",
            "agregale",
            "agregamelo",
            "agregamela",
            "agregalos",
            "agregalas",
            "dale agregalo",
            "dale agregamelo",
            "dale agregale",
            "si agregalo",
            "si agregamelo",
            "si agregala",
            "agregalo al carrito",
            "agregamelo al carrito",
            "ponelo en el carrito",
            "ponela en el carrito",
            "metelo al carrito",
            "metela al carrito",
        ]
    ) or normalized in {"dale", "si", "ok", "oka", "va", "bueno"}


def _has_explicit_add_to_cart_intent(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return False
    if _is_implicit_add_to_cart_message(message):
        return True
    return bool(
        re.search(
            r"\b(?:agrega|agregame|agregar|suma|sumame|sumar|pon|poneme|poner|mete|meteme|anade|añade|llevo)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def _has_explicit_cart_change_intent(message: str, mode: str) -> bool:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return False
    if mode == "remove":
        return bool(
            re.search(
                r"\b(?:quita|quitame|quitar|saca|sacame|sacar|remueve|remover|elimina|eliminar|borra|borrar)\b",
                normalized,
                flags=re.IGNORECASE,
            )
        )
    return bool(
        re.search(
            r"\b(?:deja|dejame|dejar)\b.*\b(?:solo|solamente|en)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def _is_affirmative_followup_message(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return False
    return normalized in {
        "si",
        "si dale",
        "dale",
        "ok",
        "oka",
        "va",
        "bueno",
        "de una",
        "continuemos",
        "sigamos",
        "si por favor",
    }


def _product_lookup_queries_from_message(message: str) -> list[str]:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return []
    cleaned = _extract_widget_product_lookup_query(message)
    if not cleaned:
        return []
    parts = [part.strip() for part in re.split(r"\s+(?:o|u|y|e)\s+", cleaned) if part.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for part in parts or [cleaned]:
        if len(part) < 2:
            continue
        if part not in seen:
            seen.add(part)
            unique.append(part)
    return unique


def _recent_products_for_llm(session_id: str) -> list[dict[str, Any]]:
    recent_products = _recent_commerce_products(session_id)
    serialized: list[dict[str, Any]] = []
    for index, product in enumerate(recent_products[:6], start=1):
        if not isinstance(product, dict):
            continue
        name = str(product.get("name") or "").strip()
        if not name:
            continue
        serialized.append(
            {
                "position": index,
                "name": name,
                "price": str(product.get("price") or "").strip(),
                "stock": str(product.get("stock") or "").strip(),
            }
        )
    return serialized


def _payload_product_names(payload: dict[str, Any] | None) -> list[str]:
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


def _update_agent_memory_from_payload(
    *,
    agent_id: str,
    company_id: str,
    session_id: str,
    user_message: str,
    answer: str,
    payload: dict[str, Any] | None,
    fallback_intent: str | None = None,
    fallback_tool: str | None = None,
) -> None:
    if agent_service is None or not session_id:
        return
    intent_label = ""
    if isinstance(payload, dict):
        intent_label = str(payload.get("intent_label") or fallback_intent or "").strip()
    tool_name = fallback_tool or ""
    product_queries = _product_lookup_queries_from_message(user_message)
    selected_products = _payload_product_names(payload)
    shipping_preference = user_message if any(token in _normalize_widget_text(user_message) for token in ["envio", "despacho", "retiro", "comuna"]) else None
    payment_preference = user_message if any(token in _normalize_widget_text(user_message) for token in ["pago", "tarjeta", "transferencia", "link de pago"]) else None
    pickup_location_label = _extract_pickup_location(user_message) or None
    delivery_address = _extract_address(user_message) or None
    delivery_address_confirmed = True if isinstance(payload, dict) and str(payload.get("intent_label") or "").strip() == "delivery_address_confirmed" else None
    invoice_data = _extract_invoice_data(user_message, session_id=session_id)
    invoice_type = invoice_data.get("invoice_type")
    invoice_rut = invoice_data.get("rut")
    invoice_business_name = invoice_data.get("business_name")
    invoice_address = invoice_data.get("invoice_address")
    customer_authenticated = True if _is_login_confirmed_message(user_message) else None
    if customer_authenticated is None and isinstance(payload, dict):
        intent = str(payload.get("intent_label") or "").strip()
        if intent in {"checkout_auth_confirmed", "checkout_otp_sent", "checkout_otp_invalid"}:
            customer_authenticated = intent == "checkout_auth_confirmed"
    try:
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
            customer_authenticated=customer_authenticated,
            order_reference=None,
            workflow_stage=str((payload or {}).get("workflow_stage") or "").strip() or None,
            pending_next_step=str((payload or {}).get("pending_next_step") or "").strip() or None,
            checkout_stage=str((payload or {}).get("checkout_stage") or "").strip() or None,
            otp_email=str((payload or {}).get("otp_email") or "").strip() or None,
            authenticated_at=str((payload or {}).get("authenticated_at") or "").strip() or None,
            reset_workflow=bool((payload or {}).get("reset_workflow")),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent_summary_update_failed agent_id=%s company_id=%s session_id=%s detail=%s",
            agent_id,
            company_id,
            session_id,
            exc,
        )


def _agent_summary_context(company_id: str, agent_id: str, session_id: str) -> str:
    if agent_service is None or not session_id:
        return ""
    try:
        return agent_service.get_session_summary_text(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent_summary_context_failed agent_id=%s company_id=%s session_id=%s detail=%s",
            agent_id,
            company_id,
            session_id,
            exc,
        )
        return ""


def _agent_workflow_state(company_id: str, agent_id: str, session_id: str) -> dict[str, str]:
    if agent_service is None or not session_id:
        return {}
    try:
        summary = agent_service.get_session_summary(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
        )
        customer_authenticated = summary.customer_authenticated
        if customer_authenticated and summary.authenticated_at:
            try:
                authed_at = datetime.fromisoformat(summary.authenticated_at)
                if (datetime.now(UTC) - authed_at).total_seconds() > 900:
                    customer_authenticated = False
            except (ValueError, TypeError):
                pass
        return {
            "stage": summary.funnel_stage,
            "checkout_stage": summary.checkout_stage,
            "pending_next_step": summary.pending_next_step,
            "selected_products": summary.selected_products,
            "shipping_preference": summary.shipping_preference,
            "pickup_location_label": summary.pickup_location_label,
            "delivery_address": summary.delivery_address,
            "delivery_address_confirmed": "true" if summary.delivery_address_confirmed else "",
            "invoice_type": summary.invoice_type,
            "invoice_rut": summary.invoice_rut,
            "invoice_business_name": summary.invoice_business_name,
            "invoice_address": summary.invoice_address,
            "payment_preference": summary.payment_preference,
            "customer_authenticated": "true" if customer_authenticated else "",
            "order_reference": summary.order_reference,
            "otp_email": summary.otp_email,
            "authenticated_at": summary.authenticated_at,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent_workflow_state_failed agent_id=%s company_id=%s session_id=%s detail=%s",
            agent_id,
            company_id,
            session_id,
            exc,
        )
        return {}


def _workflow_state_customer_authenticated(workflow_state: dict[str, str] | None) -> bool:
    raw = str((workflow_state or {}).get("customer_authenticated") or "").strip().lower()
    return raw in {"1", "true", "yes", "si"}


def _workflow_state_bool(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "si"}


def _resolve_affirmative_workflow_followup(
    *,
    message: str,
    workflow_state: dict[str, str] | None,
) -> dict[str, Any] | None:
    if not _is_affirmative_followup_message(message):
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
            "workflow_action": _workflow_action("choose_shipping_method"),
        }
    if effective_next in {"payment_selection", "payment"}:
        return {
            "answer": "Perfecto. Para seguir con el pago, te puedo mostrar medios disponibles o generar el siguiente paso si ya tienes el carrito listo.",
            "intent_label": "payment_options",
            "workflow_stage": "payment_selection",
            "pending_next_step": "payment_selection",
            "checkout_stage": "payment_method_pending",
            "workflow_action": _workflow_action("choose_payment_method"),
        }
    return None


def _create_address_for_user(
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


def _canonical_tool_succeeded(result: Any, expected_statuses: set[str] | None = None) -> bool:
    if not isinstance(result, dict) or not result.get("ok"):
        return False
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if data.get("ok") is True:
        return True
    status = str(data.get("status") or result.get("code") or result.get("status") or "").strip().lower()
    if expected_statuses and status in expected_statuses:
        return True
    return status in {"ok", "sent", "verified", "success", "valid"}


def _resolve_checkout_workflow_followup(
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
    logger.warning(
        "checkout_followup_state session_id=%s checkout_stage=%s pending_next_step=%s message=%s otp_email=%s",
        session_id, current_checkout_stage, current_pending_next_step, message,
        str((workflow_state or {}).get("otp_email") or ""),
    )
    _trace_route(
        "checkout_followup.check_stage",
        session_id=session_id,
        current_stage=current_checkout_stage,
        pending_next_step=current_pending_next_step,
        is_email=_is_email_message(message),
    )

    if current_pending_next_step in {"auth_confirmation", "auth_pending"} and _is_email_message(message):
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
                    "send_verification_code_ok session_id=%s email=%s result=%s",
                    session_id, message.strip(), result,
                )
                send_ok = _canonical_tool_succeeded(result, expected_statuses={"sent", "ok", "success"})
            except Exception as exc:
                logger.warning("send_verification_code_failed session_id=%s email=%s detail=%s", session_id, message.strip(), exc)
        if not send_ok:
            return {
                "answer": "No pude enviar el código de verificación. Probá de nuevo o avisame si querés reintentar con otro correo.",
                "intent_label": "checkout_otp_send_failed",
                "workflow_stage": "checkout_ready",
                "checkout_stage": "auth_pending",
                "pending_next_step": "auth_confirmation",
                "workflow_action": _workflow_action("otp_send_failed"),
            }
        return {
            "answer": f"Te enviamos un codigo de verificacion a {message.strip()}. Ingresalo aca para continuar.",
            "intent_label": "checkout_otp_sent",
            "workflow_stage": "checkout_ready",
            "checkout_stage": "otp_pending",
            "pending_next_step": "otp_verification",
            "otp_email": message.strip(),
            "workflow_action": _workflow_action("otp_sent"),
        }

    if current_pending_next_step == "otp_verification" or current_checkout_stage == "otp_pending":
        otp_ok = False
        otp_email = str((workflow_state or {}).get("otp_email") or "").strip()
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
                    "verify_verification_code_result session_id=%s code=%s result=%s",
                    session_id, message.strip(), result,
                )
                if _canonical_tool_succeeded(result, expected_statuses={"verified", "valid", "ok", "success"}):
                    otp_ok = True
            except Exception as exc:
                logger.warning("verify_verification_code_failed session_id=%s code=%s detail=%s", session_id, message.strip(), exc)
        if not otp_ok:
            return {
                "answer": "El codigo ingresado no es valido. Intenta de nuevo o escribe tu correo para reenviar el codigo.",
                "intent_label": "checkout_otp_invalid",
                "workflow_stage": "checkout_ready",
                "checkout_stage": "otp_pending",
                "pending_next_step": "otp_verification",
                "workflow_action": _workflow_action("otp_invalid"),
            }
        return {
            "answer": "Perfecto, ya estas autenticado. Ahora dime si prefieres retiro en tienda o despacho.",
            "intent_label": "checkout_auth_confirmed",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "shipping_method_pending",
            "pending_next_step": "shipping_selection",
            "authenticated_at": datetime.now(UTC).isoformat(),
            "workflow_action": _workflow_action("auth_confirmed", authenticated=True),
        }

    if _is_login_confirmed_message(message):
        return {
            "answer": "Perfecto, tomo que ya iniciaste sesion. Ahora dime si prefieres retiro en tienda o despacho.",
            "intent_label": "checkout_auth_confirmed",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "shipping_method_pending",
            "pending_next_step": "shipping_selection",
            "authenticated_at": datetime.now(UTC).isoformat(),
            "workflow_action": _workflow_action("auth_confirmed", authenticated=True),
        }

    pickup_location = _extract_pickup_location(message)
    if pickup_location:
        return {
            "answer": f"Perfecto, dejo retiro en {pickup_location}. Si quieres, el siguiente paso es revisar pago.",
            "intent_label": "pickup_location_selected",
            "workflow_stage": "payment_selection",
            "checkout_stage": "pickup_location_selected",
            "pending_next_step": "payment_selection",
            "workflow_action": _workflow_action(
                "pickup_location_selected",
                pickup_location_label=pickup_location,
            ),
        }

    if _wants_pickup(message):
        return {
            "answer": "Perfecto, podemos seguir con retiro. Dime en que tienda o punto de retiro quieres retirar.",
            "intent_label": "pickup_selected",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "pickup_location_pending",
            "pending_next_step": "shipping_selection",
            "workflow_action": _workflow_action("choose_pickup_location"),
        }

    existing_address = str((workflow_state or {}).get("delivery_address") or "").strip()
    address_confirmed = _workflow_state_bool((workflow_state or {}).get("delivery_address_confirmed"))

    if existing_address and _is_address_confirmation(message):
        _create_address_for_user(
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
            "workflow_action": _workflow_action(
                "delivery_address_confirmed",
                delivery_address=existing_address,
            ),
        }

    if existing_address and _is_address_correction(message):
        return {
            "answer": "Dime la direccion correcta para el despacho.",
            "intent_label": "delivery_address_correction",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "delivery_address_pending",
            "pending_next_step": "delivery_address",
            "workflow_action": _workflow_action("delivery_address_correction"),
        }

    address = _extract_address(message)
    if address:
        return {
            "answer": f"Encontre esta direccion de despacho:\n{address}\n\nEsta correcta?",
            "intent_label": "delivery_address_proposed",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "delivery_address_proposed",
            "pending_next_step": "delivery_address_confirmation",
            "workflow_action": _workflow_action(
                "delivery_address_proposed",
                delivery_address=address,
            ),
        }

    if _wants_delivery(message):
        return {
            "answer": "Perfecto, dime la direccion donde quieres recibir el pedido (calle, numero, comuna).",
            "intent_label": "delivery_selected",
            "workflow_stage": "shipping_selection",
            "checkout_stage": "delivery_address_pending",
            "pending_next_step": "delivery_address",
            "workflow_action": _workflow_action("choose_delivery_address"),
        }

    past_shipping = current_checkout_stage in {"delivery_address_confirmed", "pickup_location_selected", "delivery_address_proposed", "delivery_address_confirmation"}
    current_invoice_type = str((workflow_state or {}).get("invoice_type") or "").strip().lower()
    current_rut = str((workflow_state or {}).get("invoice_rut") or "").strip()
    current_business_name = str((workflow_state or {}).get("invoice_business_name") or "").strip()
    current_invoice_address = str((workflow_state or {}).get("invoice_address") or "").strip()

    if past_shipping and not current_invoice_type:
        invoice_data = _extract_invoice_data(message, session_id=session_id)
        factura_match = invoice_data.get("invoice_type") == "factura"
        boleta_match = invoice_data.get("invoice_type") == "boleta"
        if factura_match:
            rut = invoice_data.get("rut") or current_rut
            business_name = invoice_data.get("business_name") or current_business_name
            invoice_addr = invoice_data.get("invoice_address") or current_invoice_address
            delivery_addr = str((workflow_state or {}).get("delivery_address") or "").strip()
            if not rut or not business_name:
                return {
                    "answer": "Perfecto. Necesito tu RUT y razon social para la factura. Ej: RUT 76.123.456-7, Razon social: Empresa SAC",
                    "intent_label": "invoice_data_pending",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "invoice_data_pending",
                    "pending_next_step": "invoice_data",
                    "workflow_action": _workflow_action("request_invoice_data"),
                }
            if not invoice_addr and delivery_addr:
                return {
                    "answer": f"La direccion de facturacion es la misma de despacho?\n{delivery_addr}",
                    "intent_label": "invoice_address_pending",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "invoice_address_pending",
                    "pending_next_step": "invoice_address",
                    "workflow_action": _workflow_action(
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
                    "workflow_action": _workflow_action("request_invoice_address"),
                }
            return {
                "answer": f"Perfecto, factura a nombre de {business_name}, RUT {rut}. Direccion: {invoice_addr}. Pasamos al pago?",
                "intent_label": "invoice_data_confirmed",
                "workflow_stage": "payment_selection",
                "checkout_stage": "invoice_data_complete",
                "pending_next_step": "payment_selection",
                "workflow_action": _workflow_action(
                    "invoice_data_confirmed",
                    rut=rut,
                    business_name=business_name,
                    invoice_address=invoice_addr,
                ),
            }
        if boleta_match:
            return {
                "answer": "Perfecto, se emite boleta. Pasamos al pago?",
                "intent_label": "invoice_boleta",
                "workflow_stage": "payment_selection",
                "checkout_stage": "invoice_boleta_selected",
                "pending_next_step": "payment_selection",
                "workflow_action": _workflow_action("invoice_boleta"),
            }

    if current_invoice_type == "factura" and current_checkout_stage in {"invoice_data_pending", "delivery_address_confirmed", "pickup_location_selected"}:
        invoice_data = _extract_invoice_data(message, session_id=session_id)
        rut = invoice_data.get("rut") or current_rut
        business_name = invoice_data.get("business_name") or current_business_name
        invoice_addr = invoice_data.get("invoice_address") or current_invoice_address
        delivery_addr = str((workflow_state or {}).get("delivery_address") or "").strip()
        has_new_data = bool(rut) or bool(business_name) or bool(invoice_addr)
        if has_new_data:
            if not rut:
                return {"answer": "Falta el RUT para la factura. Ej: 76.123.456-7"}
            if not business_name:
                return {"answer": f"Falta la razon social. RUT: {rut}. Cual es el nombre de la empresa?"}
            if not invoice_addr and delivery_addr:
                return {
                    "answer": f"La direccion de facturacion es la misma de despacho?\n{delivery_addr}",
                    "intent_label": "invoice_address_pending",
                    "workflow_stage": "payment_selection",
                    "checkout_stage": "invoice_address_pending",
                    "pending_next_step": "invoice_address",
                    "workflow_action": _workflow_action("request_invoice_address", delivery_address=delivery_addr),
                }
            if not invoice_addr:
                return {"answer": "Dime la direccion de facturacion (calle, numero, comuna)."}
            return {
                "answer": f"Factura: {business_name}, RUT {rut}, direccion {invoice_addr}. Pasamos al pago?",
                "intent_label": "invoice_data_confirmed",
                "workflow_stage": "payment_selection",
                "checkout_stage": "invoice_data_complete",
                "pending_next_step": "payment_selection",
                "workflow_action": _workflow_action(
                    "invoice_data_confirmed", rut=rut, business_name=business_name, invoice_address=invoice_addr,
                ),
            }

    if current_checkout_stage == "invoice_address_pending":
        delivery_addr = str((workflow_state or {}).get("delivery_address") or "").strip()
        if _is_address_confirmation(message) and delivery_addr:
            return {
                "answer": f"Perfecto, uso la misma direccion de despacho: {delivery_addr}. Pasamos al pago?",
                "intent_label": "invoice_address_confirmed",
                "workflow_stage": "payment_selection",
                "checkout_stage": "invoice_data_complete",
                "pending_next_step": "payment_selection",
                "workflow_action": _workflow_action(
                    "invoice_address_confirmed", invoice_address=delivery_addr,
                ),
            }
        invoice_data = _extract_invoice_data(message, session_id=session_id)
        invoice_addr = invoice_data.get("invoice_address") or _extract_address(message)
        if invoice_addr:
            return {
                "answer": f"Direccion de facturacion: {invoice_addr}. Pasamos al pago?",
                "intent_label": "invoice_address_confirmed",
                "workflow_stage": "payment_selection",
                "checkout_stage": "invoice_data_complete",
                "pending_next_step": "payment_selection",
                "workflow_action": _workflow_action(
                    "invoice_address_confirmed", invoice_address=invoice_addr,
                ),
            }
        if _wants_delivery(message) or any(token in _normalize_widget_text(message) for token in ["misma", "igual", "misma direccion"]):
            return {
                "answer": f"Perfecto, uso la direccion de despacho. Pasamos al pago?",
                "intent_label": "invoice_address_confirmed",
                "workflow_stage": "payment_selection",
                "checkout_stage": "invoice_data_complete",
                "pending_next_step": "payment_selection",
                "workflow_action": _workflow_action(
                    "invoice_address_confirmed", invoice_address=delivery_addr or "",
                ),
            }

    return None


def _personalize_agent_freeform_response(
    *,
    agent_name: str,
    company_id: str,
    message: str,
    route: str | None,
    default_answer: str,
) -> str:
    normalized_route = (route or "").strip().lower()

    if normalized_route == "greeting":
        return default_answer

    return default_answer


def _parse_widget_quantity(text: str) -> int:
    tokens = _normalize_widget_text(text).split()
    for token in tokens[:4]:
        if token.isdigit():
            return max(1, min(99, int(token)))
        if token in _WIDGET_QUANTITY_WORDS:
            return _WIDGET_QUANTITY_WORDS[token]
    return 1


def _is_remove_from_cart_message(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return False
    return any(
        phrase in normalized
        for phrase in [
            "quita ",
            "quitame ",
            "saca ",
            "sacame ",
            "remueve ",
            "elimina ",
            "borra ",
        ]
    )


def _is_set_cart_quantity_message(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return False
    return any(
        phrase in normalized
        for phrase in [
            "deja solo ",
            "deja en ",
            "deja solo",
            "dejame solo ",
        ]
    )


def _is_clear_cart_message(message: str) -> bool:
    normalized = _normalize_widget_text(message)
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


def _is_login_confirmed_message(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    return normalized in {
        "ya inicie sesion",
        "ya inicié sesion",
        "ya inicie login",
        "ya hice login",
        "ya me loguee",
        "ya me autentique",
        "ya estoy logueado",
    }


EMAIL_RE = re.compile(r"^[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+$", re.IGNORECASE)


def _is_email_message(message: str) -> bool:
    if not message or not message.strip():
        return False
    return bool(EMAIL_RE.match(message.strip()))


def _extract_pickup_location(message: str) -> str:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return ""
    patterns = [
        r"(?:retiro en|pickup en|recoger en)\s+(.+)$",
        r"(?:sucursal|tienda|local)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip()
    return ""


def _wants_pickup(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    return any(token in normalized for token in ["retiro", "pickup", "recoger en tienda", "retiro en tienda"])


def _wants_delivery(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    return any(token in normalized for token in ["despacho", "domicilio", "delivery", "envio", "enviar", "enviame", "llevar a casa"])


def _extract_address(message: str) -> str:
    raw = (message or "").strip()
    if not raw:
        return ""
    normalized = _normalize_widget_text(raw)
    patterns = [
        r"(?:direccion|dir|envio a|despacho a|domicilio en|para|calle|av|avda|pje|pasaje)\s+(.+)$",
        r"^(.+?\d{3,}.*)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            candidate = str(match.group(1) or "").strip().rstrip(".,;")
            if len(candidate) >= 8:
                return candidate
    return ""


def _is_address_confirmation(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    return normalized in {
        "si", "si correcta", "si esta correcta", "correcto", "bien", "ok", "dale",
        "confirmo", "confirmar", "confirmada", "si esa es",
    }


def _is_address_correction(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    return any(token in normalized for token in [
        "no", "corregir", "cambiar", "modificar", "esa no es", "direccion incorrecta",
        "esa no", "no correcta", "no esa",
    ])


def _extract_invoice_type(message: str) -> str:
    normalized = _normalize_widget_text(message)
    if any(token in normalized for token in ["factura", "facturar", "con factura"]):
        return "factura"
    if any(token in normalized for token in ["boleta", "solo boleta", "sin factura"]):
        return "boleta"
    return ""


def _extract_rut(message: str) -> str:
    match = re.search(r'\b(\d{1,2}\.?\d{3}\.?\d{3}[-]?[\dkK])\b', message or "")
    if match:
        return match.group(1).strip()
    match = re.search(r'\b(\d{7,8}[-]?[\dkK])\b', message or "")
    if match:
        return match.group(1).strip()
    return ""


def _extract_invoice_business_name(message: str) -> str:
    patterns = [
        r"(?:razon social|razon\s+social|nombre empresa|nombre\s+empresa|empresa|sociedad)\s*:?\s*(.+?)(?:,\s*rut|,\s*direccion|$)",
        r"(?:rut|r\.u\.t)\s*:?\s*\d.*?\s+(.+?)(?:,\s*|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message or "", flags=re.IGNORECASE)
        if match:
            candidate = str(match.group(1) or "").strip().rstrip(".,;")
            if candidate:
                return candidate
    return ""


def _extract_invoice_address(message: str) -> str:
    patterns = [
        r"(?:direccion fiscal|direccion facturacion|domicilio fiscal|dir factura)\s*:?\s*(.+?)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, message or "", flags=re.IGNORECASE)
        if match:
            candidate = str(match.group(1) or "").strip().rstrip(".,;")
            if candidate:
                return candidate
    return ""


def _is_boleta_request(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    return any(token in normalized for token in ["boleta", "solo boleta", "sin factura"])


def _is_factura_request(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    return any(token in normalized for token in ["factura", "facturar", "con factura", "necesito factura"])


def _workflow_action(action_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": action_type, "payload": payload}


def _is_checkout_redirect_channel(channel: str | None) -> bool:
    normalized = (channel or "").strip().lower()
    return normalized in {"widget_web", "web", "widget_public"}


def _is_checkout_request_message(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return False
    return any(
        token in normalized
        for token in [
            "quiero pagar",
            "ir a pagar",
            "pagar",
            "checkout",
            "finalizar compra",
            "terminar compra",
            "comprar ahora",
            "link de pago",
        ]
    )


def _extract_widget_cart_change_requests(
    message: str,
    *,
    mode: str,
) -> list[dict[str, Any]]:
    normalized = _normalize_widget_text(message)
    _trace_route(
        "cart_change.extract.start",
        mode=mode,
        message=message,
        normalized=normalized,
    )
    if not normalized:
        return []
    if not _has_explicit_cart_change_intent(message, mode):
        _trace_route(
            "cart_change.extract.skip_no_explicit_intent",
            mode=mode,
            message=message,
            normalized=normalized,
        )
        return []

    segments = [part.strip() for part in re.split(r"\s+(?:y|e|ademas|tambien)\s+", normalized) if part.strip()]
    requests: list[dict[str, Any]] = []
    for segment in segments:
        _trace_route(
            "cart_change.extract.segment",
            mode=mode,
            segment=segment,
        )
        if mode == "remove":
            cleaned = re.sub(
                r"\b(?:quita|quitame|quitar|saca|sacame|sacar|remueve|remover|elimina|eliminar|borra|borrar|del|de|la|el|los|las|carrito)\b",
                " ",
                segment,
                flags=re.IGNORECASE,
            )
        else:
            cleaned = re.sub(
                r"\b(?:deja|dejame|dejar|solo|solamente|en|con|la|el|los|las|carrito)\b",
                " ",
                segment,
                flags=re.IGNORECASE,
            )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        _trace_route(
            "cart_change.extract.cleaned",
            mode=mode,
            segment=segment,
            cleaned=cleaned,
        )
        if not cleaned:
            continue

        quantity = _parse_widget_quantity(segment)
        product_query = re.sub(r"^\d+\s+", "", cleaned).strip()
        product_query = re.sub(r"^(un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+", "", product_query).strip()
        if not product_query:
            continue
        requests.append({"quantity": quantity, "product_query": product_query})
    _trace_route(
        "cart_change.extract.result",
        mode=mode,
        requests=requests,
    )
    return requests


def _extract_widget_cart_requests(message: str) -> list[dict[str, Any]]:
    normalized = _normalize_widget_text(message)
    _trace_route(
        "cart.extract.start",
        message=message,
        normalized=normalized,
        implicit_add=_is_implicit_add_to_cart_message(message),
    )
    if not normalized:
        return []
    if not _has_explicit_add_to_cart_intent(message):
        _trace_route(
            "cart.extract.skip_no_explicit_intent",
            message=message,
            normalized=normalized,
        )
        return []

    segments = [part.strip() for part in re.split(r"\s+(?:y|e|ademas|tambien)\s+", normalized) if part.strip()]
    requests: list[dict[str, Any]] = []
    for segment in segments:
        has_add_verb = bool(
            re.search(
                r"\b(?:agrega|agregame|agregar|suma|sumame|sumar|pon|poneme|poner|mete|meteme|anade|llevo|quiero)\b",
                segment,
                flags=re.IGNORECASE,
            )
        )
        _trace_route(
            "cart.extract.segment",
            segment=segment,
            has_add_verb=has_add_verb,
        )
        cleaned = re.sub(
            r"\b(?:agrega|agregame|agregar|suma|sumame|sumar|pon|poneme|poner|mete|meteme|anade|llevo|quiero|porfa|por favor|al|carrito|el|la|los|las)\b",
            " ",
            segment,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        _trace_route(
            "cart.extract.cleaned",
            segment=segment,
            cleaned=cleaned,
            has_add_verb=has_add_verb,
        )
        if not cleaned:
            continue

        quantity = _parse_widget_quantity(segment)
        product_query = re.sub(r"^\d+\s+", "", cleaned).strip()
        product_query = re.sub(r"^(un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+", "", product_query).strip()
        if not product_query:
            continue
        requests.append({"quantity": quantity, "product_query": product_query})
    _trace_route(
        "cart.extract.result",
        message=message,
        requests=requests,
    )
    return requests


def _extract_widget_product_lookup_query(message: str) -> str:
    normalized = _normalize_widget_text(message)
    _trace_route(
        "lookup.extract.start",
        message=message,
        normalized=normalized,
    )
    if not normalized:
        return ""

    cleaned = re.sub(
        r"\b(?:hola|buenas|buenos dias|buen dia|quiero saber|queria saber|quisiera saber|me gustaria saber|podrias decirme|podrias mostrarme|me muestras|mostrarme|ver|buscar|busco|tienen|tiene|tenes|tenian|tenia|hay|habia|si|si tienen|si hay|si vende|disponible|disponibles|stock|precio|cuesta|por favor|porfa|el|la|los|las|un|una|unos|unas)\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    _trace_route(
        "lookup.extract.result",
        message=message,
        cleaned=cleaned,
    )
    return cleaned


def _should_try_llm_commerce_parser(intent_label: str | None, message: str) -> bool:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return False
    return True


def _parse_commerce_intent_with_openai(
    message: str,
    *,
    session_id: str,
    intent_label: str | None = None,
    channel: str | None = None,
    response_style_context: str | None = None,
    workflow_context: str | None = None,
) -> dict[str, Any] | None:
    if not _should_try_llm_commerce_parser(intent_label, message):
        return None

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    recent_products = _recent_products_for_llm(session_id)
    request_payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un planner de workflow comercial para un agente conversacional de e-commerce. "
                    "Debes detectar la intencion, decidir si conviene responder con texto, pedir aclaracion o ejecutar un tool, "
                    "y definir la forma de responder de manera breve, comercial y accionable. "
                    "Devuelve SOLO JSON valido con esta forma exacta: "
                    "{\"intent\":string,\"confidence\":number,\"query\":string,\"items\":[{\"query\":string,\"quantity\":number}],\"tool\":string,\"tool_arguments\":object,\"needs_clarification\":boolean,\"clarification_question\":string,\"customer_goal\":string,\"response_style\":{\"stage\":string,\"tone\":string,\"next_step\":string,\"format\":string}}. "
                    "Intent permitidos: none, product_lookup, add_to_cart, remove_from_cart, set_cart_quantity, clear_cart, cart_status, shipping_options, payment_options, order_status, create_payment_link, create_order_draft, recipe_recommendation. "
                    "Tools permitidos: none, get_product_availability, get_order_status, get_shipping_options, get_payment_options, create_payment_link, create_order_draft. "
                    "Usa el workflow_context como prioridad para interpretar la intencion. Si workflow_context indica checkout_stage=auth_pending, el mensaje actual debe tratarse como un correo para enviar el codigo. Si checkout_stage=otp_pending, el mensaje actual debe tratarse como el valor a verificar con verify_verification_code usando otp_email persistido. "
                    "Extrae productos y cantidades solo cuando el usuario lo exprese de forma clara en el mensaje y en contexto de compra. Si no hay cantidad explicita usa 1. "
                    "Si pide quitar unidades del carrito usa remove_from_cart. Si pide dejar una cantidad exacta usa set_cart_quantity. Si pide vaciar el carrito usa clear_cart. Si pregunta por el carrito actual, resumen del carrito o como va el carrito, usa cart_status y NO order_status. "
                    "Si el mensaje pregunta disponibilidad, precio, stock o catalogo usa get_product_availability. "
                    "Si pregunta estado de pedido usa get_order_status y extrae order_reference cuando exista. "
                    "Si quiere pagar ahora o generar link usa create_payment_link solo si ya hay productos/orden suficientes, si no pide el dato faltante. "
                    "Si quiere cerrar pedido, reservar o generar borrador usa create_order_draft solo si hay items claros. "
                    "Si pregunta medios de pago usa get_payment_options. Si pregunta despacho, envio o retiro usa get_shipping_options. "
                    "Si el mensaje usa referencias como 'agregamelo', 'ese', 'el primero', 'el segundo', debes resolverlas usando recent_products si existe contexto. "
                    "Si el usuario responde solo con una cantidad como '1', '2' o 'quiero 1' luego de ver un producto o un listado, interpretalo como seguimiento de compra y usa recent_products o workflow_context para decidir add_to_cart o set_cart_quantity. "
                    "No inventes datos faltantes. Si faltan datos criticos marca needs_clarification=true y escribe clarification_question concreta."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": message,
                        "intent_label_hint": intent_label or "",
                        "channel": channel or "",
                        "response_style_context": response_style_context or "",
                        "workflow_context": workflow_context or "",
                        "recent_products": recent_products,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("commerce_intent_llm_failed session_id=%s detail=%s", session_id, exc)
        return None

    try:
        payload = json.loads(raw)
        content = str((((payload.get("choices") or [None])[0] or {}).get("message") or {}).get("content") or "").strip()
        parsed = json.loads(content) if content else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("commerce_intent_llm_invalid session_id=%s detail=%s", session_id, exc)
        return None

    if not isinstance(parsed, dict):
        return None

    logger.info(
        "commerce_intent_llm_ok session_id=%s intent=%s tool=%s confidence=%s query=%s items=%s recent_products=%s",
        session_id,
        parsed.get("intent"),
        parsed.get("tool"),
        parsed.get("confidence"),
        parsed.get("query"),
        parsed.get("items"),
        len(recent_products),
    )
    return parsed


def _parse_invoice_data_with_openai(
    message: str,
    *,
    session_id: str,
) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

    request_payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un extractor de datos de facturacion para e-commerce chileno. "
                    "Del mensaje del usuario extrae SOLO datos de facturacion. "
                    "Devuelve SOLO JSON valido con estos campos:\n"
                    "{\n"
                    '  "invoice_type": "factura" | "boleta" | null,\n'
                    '  "rut": "RUT chileno formateado" | null,\n'
                    '  "business_name": "razon social o nombre empresa" | null,\n'
                    '  "invoice_address": "direccion fiscal" | null,\n'
                    '  "use_delivery_address": true | false\n'
                    "}\n\n"
                    "Reglas:\n"
                    "- invoice_type: 'factura' si pide facturar, 'boleta' si dice boleta o no menciona tipo\n"
                    "- RUT: formato XX.XXX.XXX-X o XXXXXXXXX-X, extraer aunque vaya pegado\n"
                    "- business_name: razon social, nombre de empresa, o persona juridica\n"
                    "- invoice_address: direccion fiscal solo si la da explicitamente\n"
                    "- use_delivery_address: true SOLO si el usuario confirma usar la direccion de despacho "
                    "cuando se le pregunta (dice 'si', 'la misma', 'igual', 'confirmo'). false en caso contrario.\n"
                    "- Cualquier campo que no aparezca en el mensaje debe ir como null.\n"
                    "- No inventes datos."
                ),
            },
            {
                "role": "user",
                "content": message,
            },
        ],
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:
        logger.warning("invoice_llm_failed session_id=%s detail=%s", session_id, exc)
        return None

    try:
        payload = json.loads(raw)
        content = str((((payload.get("choices") or [None])[0] or {}).get("message") or {}).get("content") or "").strip()
        parsed = json.loads(content) if content else {}
    except Exception as exc:
        logger.warning("invoice_llm_invalid session_id=%s detail=%s", session_id, exc)
        return None

    if not isinstance(parsed, dict):
        return None

    logger.info(
        "invoice_llm_ok session_id=%s invoice_type=%s rut=%s business_name=%s address=%s use_delivery=%s",
        session_id,
        parsed.get("invoice_type"),
        parsed.get("rut"),
        parsed.get("business_name"),
        parsed.get("invoice_address"),
        parsed.get("use_delivery_address"),
    )
    return parsed


def _extract_invoice_data(
    message: str,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "invoice_type": None,
        "rut": None,
        "business_name": None,
        "invoice_address": None,
        "use_delivery_address": False,
    }

    if session_id:
        llm_result = _parse_invoice_data_with_openai(message, session_id=session_id)
        if isinstance(llm_result, dict):
            for key in ("invoice_type", "rut", "business_name", "invoice_address"):
                val = llm_result.get(key)
                if val and str(val).strip():
                    result[key] = str(val).strip()
            use_delivery = llm_result.get("use_delivery_address")
            if isinstance(use_delivery, bool):
                result["use_delivery_address"] = use_delivery
            return result

    result["invoice_type"] = _extract_invoice_type(message) or None
    result["rut"] = _extract_rut(message) or None
    result["business_name"] = _extract_invoice_business_name(message) or None
    result["invoice_address"] = _extract_invoice_address(message) or None
    return result


def _cart_requests_from_llm_intent(parsed: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict):
        return []
    if str(parsed.get("intent") or "").strip().lower() not in {"add_to_cart", "remove_from_cart", "set_cart_quantity", "clear_cart"}:
        return []
    items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
    requests: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        quantity_raw = item.get("quantity")
        quantity = int(quantity_raw) if isinstance(quantity_raw, (int, float)) else 1
        quantity = max(1, min(99, quantity))
        if query:
            requests.append({"product_query": query, "quantity": quantity})
    return requests


def _product_lookup_queries_from_llm_intent(parsed: dict[str, Any] | None) -> list[str]:
    if not isinstance(parsed, dict):
        return []
    if str(parsed.get("intent") or "").strip().lower() != "product_lookup":
        return []
    queries: list[str] = []
    seen: set[str] = set()
    items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if query and query not in seen:
            seen.add(query)
            queries.append(query)
    fallback_query = str(parsed.get("query") or "").strip()
    if fallback_query and fallback_query not in seen:
        queries.append(fallback_query)
    return queries


def _is_recipe_request_message(message: str) -> bool:
    normalized = _normalize_widget_text(message)
    if not normalized:
        return False
    return any(
        token in normalized
        for token in [
            "receta",
            "recetario",
            "cocinar",
            "cocino",
            "queque",
            "torta",
            "postre",
            "hambre",
            "desayuno",
            "desayunar",
            "almuerzo",
            "almorzar",
            "cena",
            "cenar",
            "once",
        ]
    )


def _generate_recipe_plan_with_openai(message: str, session_id: str, recent_products: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _is_recipe_request_message(message):
        return None
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    recent_names = [str(item.get("name") or "").strip() for item in recent_products if isinstance(item, dict)]
    request_payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un planificador de recetas para e-commerce. "
                    "Devuelve SOLO JSON con esta forma exacta: "
                    "{\"recipes\":[{\"name\":string,\"reason\":string,\"ingredient_queries\":[string]}]}. "
                    "Sugiere maximo 2 recetas. Usa ingredientes buscables en un catalogo de supermercado. "
                    "Si el usuario pide una receta especifica como queque, priorizala. "
                    "Si menciona hambre o cocinar, propone recetas simples. "
                    "Si hay productos recientes del historial, usalos como contexto para priorizar recetas relacionadas."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": message,
                        "recent_products": recent_names[:8],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
        content = str((((payload.get("choices") or [None])[0] or {}).get("message") or {}).get("content") or "").strip()
        parsed = json.loads(content) if content else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("recipe_plan_llm_failed session_id=%s detail=%s", session_id, exc)
        return None

    if not isinstance(parsed, dict):
        return None
    logger.info("recipe_plan_llm_ok session_id=%s payload=%s", session_id, parsed)
    return parsed


def _tool_from_llm_commerce_intent(parsed: dict[str, Any] | None, session_id: str) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(parsed, dict):
        return None
    intent = str(parsed.get("intent") or "").strip().lower()
    confidence_raw = parsed.get("confidence")
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
    if confidence < 0.72:
        return None

    query = str(parsed.get("query") or "").strip()
    planned_tool = str(parsed.get("tool") or "").strip().lower()
    tool_arguments = parsed.get("tool_arguments") if isinstance(parsed.get("tool_arguments"), dict) else {}
    items = _cart_requests_from_llm_intent(parsed)

    if planned_tool in _SUPPORTED_COMMERCE_TOOLS:
        arguments = dict(tool_arguments)
        arguments.setdefault("session_id", session_id)
        if planned_tool == "get_product_availability" and not arguments.get("query") and query:
            arguments["query"] = query
        if planned_tool == "get_product_availability":
            arguments.setdefault("limit", 5)
        if planned_tool == "get_shipping_options" and "commune" not in arguments:
            arguments["commune"] = query or ""
        if planned_tool == "get_order_status":
            order_reference = str(parsed.get("order_reference") or query or "").strip()
            if order_reference:
                arguments.setdefault("order_reference", order_reference)
                arguments.setdefault("query", order_reference)
        return planned_tool, arguments

    if intent == "add_to_cart" and items:
        first = items[0]
        return "get_product_availability", {"query": first["product_query"], "limit": 5, "session_id": session_id}
    if intent == "product_lookup" and query:
        return "get_product_availability", {"query": query, "limit": 5, "session_id": session_id}
    if intent == "shipping_options":
        return "get_shipping_options", {"commune": query or "", "session_id": session_id}
    if intent in {"payment_options", "checkout"}:
        return "get_payment_options", {"session_id": session_id}
    return None


def _checkout_requests_for_workflow(message: str, session_id: str, parsed: dict[str, Any] | None) -> list[dict[str, Any]]:
    return _cart_requests_from_llm_intent(parsed)


def _resolve_checkout_items(
    *,
    company_id: str,
    user_id: str,
    channel: str,
    session_id: str,
    cart_requests: list[dict[str, Any]],
    clubhx_tools_client: ClubHxToolsClient,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    canonical_results = [
        clubhx_tools_client.execute_canonical(
            tenant_id=company_id,
            tool="get_product_availability",
            channel=channel,
            user_id=user_id,
            arguments={
                "query": str(cart_request.get("product_query") or "").strip(),
                "limit": 5,
                "session_id": session_id,
            },
        )
        for cart_request in cart_requests
        if str(cart_request.get("product_query") or "").strip()
    ]
    logger.warning(
        "commerce_checkout_resolve cart_requests=%s canonical_results_count=%s",
        cart_requests,
        len(canonical_results),
    )
    items: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    seen_products: set[str] = set()
    for cart_request, result in zip(cart_requests, canonical_results):
        if not isinstance(result, dict) or not result.get("ok"):
            logger.warning(
                "commerce_checkout_skip reason=result_not_ok cart_request=%s result=%s",
                cart_request,
                result.get("ok") if isinstance(result, dict) else type(result).__name__,
            )
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        rows = data.get("items") if isinstance(data.get("items"), list) else []
        safe_rows = [row for row in rows if isinstance(row, dict)]
        if not safe_rows:
            logger.warning(
                "commerce_checkout_skip reason=no_items cart_request=%s",
                cart_request,
            )
            continue
        first = safe_rows[0]
        product_id = str(first.get("id") or "").strip()
        checkout_product_id = str(first.get("code") or first.get("id") or "").strip()
        variant_id = str(first.get("id") or "").strip()
        name = str(first.get("name") or "Producto").strip() or "Producto"
        quantity = int(cart_request.get("quantity") or 1)

        logger.warning(
            "commerce_checkout_raw_item raw_item=%s cart_request=%s",
            {k: first.get(k) for k in ("id", "code", "name", "price", "available_units") if k in first},
            cart_request,
        )

        if not product_id:
            logger.warning(
                "commerce_checkout_skip reason=no_product_id raw_item=%s cart_request=%s",
                {k: first.get(k) for k in ("id", "code", "name") if k in first},
                cart_request,
            )
            continue
        items.append(
            {
                "product_id": checkout_product_id or product_id,
                "checkout_product_id": checkout_product_id or product_id,
                "variant_id": variant_id or product_id,
                "quantity": max(1, min(99, quantity)),
                "name": name,
            }
        )
        for row in safe_rows[:3]:
            row_id = str(row.get("id") or "").strip()
            if not row_id or row_id in seen_products:
                continue
            seen_products.add(row_id)
            products.append(_normalize_catalog_product(row))
    return items, products


def _tool_for_intent(intent_label: str, message: str, session_id: str) -> tuple[str, dict[str, Any]] | None:
    llm_commerce_intent = _parse_commerce_intent_with_openai(
        message,
        session_id=session_id,
        intent_label=intent_label,
        channel="api",
    )
    llm_tool = _tool_from_llm_commerce_intent(llm_commerce_intent, session_id)
    if llm_tool:
        return llm_tool
    return None


def _forced_commerce_tool(message: str, session_id: str) -> tuple[str, dict[str, Any]] | None:
    if not (message or "").strip():
        return None
    llm_commerce_intent = _parse_commerce_intent_with_openai(
        message,
        session_id=session_id,
        intent_label=None,
        channel="api",
    )
    llm_tool = _tool_from_llm_commerce_intent(llm_commerce_intent, session_id)
    if llm_tool:
        return llm_tool
    return None


def _effective_chat_channel(channel: str | None, default: str) -> str:
    normalized = (channel or "").strip()
    return normalized or default


def _normalize_media_filename(filename: str | None, mime_type: str | None) -> str:
    clean_name = (filename or "audio").strip() or "audio"
    if "." in clean_name:
        return clean_name
    clean_mime = (mime_type or "").strip().lower()
    if "ogg" in clean_mime:
        return f"{clean_name}.ogg"
    if "mpeg" in clean_mime or "mp3" in clean_mime:
        return f"{clean_name}.mp3"
    if "wav" in clean_mime:
        return f"{clean_name}.wav"
    if "m4a" in clean_mime or "mp4" in clean_mime:
        return f"{clean_name}.m4a"
    if "webm" in clean_mime:
        return f"{clean_name}.webm"
    return f"{clean_name}.bin"


def _build_multipart_body(fields: dict[str, str], file_field: tuple[str, str, bytes, str]) -> tuple[bytes, str]:
    boundary = f"----clasificacion-{uuid4().hex}"
    chunks: list[bytes] = []

    def add_text_field(name: str, value: str) -> None:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")

    for key, value in fields.items():
        if value:
            add_text_field(key, value)

    field_name, filename, content, mime_type = file_field
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(content)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def _transcribe_audio_bytes(
    *,
    audio_bytes: bytes,
    filename: str,
    mime_type: str | None,
    language_hint: str | None,
) -> MediaTranscriptionPayload | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        logger.warning("[transcribe] openai_api_key_missing")
        raise HTTPException(status_code=503, detail="openai_api_key_missing")

    clean_filename = _normalize_media_filename(filename, mime_type)
    clean_mime = (mime_type or "application/octet-stream").strip() or "application/octet-stream"
    fields: dict[str, str] = {
        "model": "whisper-1",
        "response_format": "verbose_json",
    }
    if language_hint and language_hint.strip():
        fields["language"] = language_hint.strip()

    logger.info(
        "[transcribe] openai_request filename=%s mime_type=%s bytes=%s language_hint=%s",
        clean_filename,
        clean_mime,
        len(audio_bytes),
        language_hint or "",
    )

    body, boundary = _build_multipart_body(fields, ("file", clean_filename, audio_bytes, clean_mime))
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        logger.warning("[transcribe] openai_http_error status=%s detail=%s", exc.code, detail[:1000])
        raise HTTPException(status_code=503, detail=f"No se pudo transcribir audio: {detail}") from exc
    except urllib.error.URLError as exc:
        logger.warning("[transcribe] openai_url_error reason=%s", exc.reason)
        raise HTTPException(status_code=503, detail=f"No se pudo conectar al servicio de transcripcion: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="Respuesta de transcripcion invalida") from exc

    text = str(payload.get("text") or "").strip()
    if not text:
        logger.warning("[transcribe] openai_empty_text filename=%s mime_type=%s", clean_filename, clean_mime)
        raise HTTPException(status_code=503, detail="openai_empty_text")

    duration_seconds = payload.get("duration")
    duration_ms = None
    if isinstance(duration_seconds, (int, float)):
        duration_ms = int(float(duration_seconds) * 1000)

    logger.info("[transcribe] openai_ok text_len=%s language=%s duration_ms=%s", len(text), payload.get("language") or "", duration_ms or 0)
    return MediaTranscriptionPayload(
        text=text,
        language=str(payload.get("language") or "").strip() or None,
        confidence=None,
        duration_ms=duration_ms,
        provider="openai",
    )


def _first_present_string(payload: Any, keys: list[str]) -> str:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            nested = _first_present_string(value, keys)
            if nested:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = _first_present_string(item, keys)
            if nested:
                return nested
    return ""


def _normalize_catalog_product(item: dict[str, Any]) -> dict[str, Any]:
    product_id = _first_present_string(item, ["id", "product_id", "variant_id", "sku", "code"])
    checkout_product_id = _first_present_string(item, ["code", "checkout_product_id", "product_id", "id", "sku"])
    variant_id = _first_present_string(item, ["variant_id", "id", "product_id", "sku", "code"])
    image_url = _first_present_string(item, ["image_url", "image", "imageUrl", "thumbnail", "thumbnail_url", "photo"])
    price = _first_present_string(item, ["price", "unit_price", "sale_price", "amount", "value"])
    stock = _first_present_string(item, ["available_units", "stock", "quantity", "available", "inventory"])
    name = _first_present_string(item, ["name", "title", "product_name", "label"]) or "Producto"
    return {
        "id": product_id,
        "checkout_product_id": checkout_product_id or product_id,
        "variant_id": variant_id or product_id,
        "name": name,
        "price": price or "N/D",
        "stock": stock or "0",
        "image_url": image_url or None,
    }


def _format_canonical_tool_answer(result: dict[str, Any]) -> str | None:
    if not result.get("ok"):
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    tool = str(result.get("tool") or "")
    if tool == "get_product_availability":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        if not items:
            return "No encontré productos con ese criterio."
        first = _normalize_catalog_product(items[0] if isinstance(items[0], dict) else {})
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
        status = _first_present_string(data, ["status", "order_status", "state"])
        order_reference = _first_present_string(data, ["order_reference", "order_id", "id", "number"])
        tracking = _first_present_string(data, ["tracking_url", "tracking_link"])
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
        url = _first_present_string(data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
        if url:
            return f"Listo, ya tengo tu link de pago: {url}"
        return "Pude generar la accion de pago, pero el proveedor no devolvio un link utilizable."
    if tool == "create_order_draft":
        draft_reference = _first_present_string(data, ["draft_id", "order_id", "order_reference", "id", "number"])
        payment_url = _first_present_string(data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
        answer = (
            f"Listo, deje creada la orden borrador {draft_reference}." if draft_reference else "Listo, deje creada la orden borrador."
        )
        if payment_url:
            answer += f" Si quieres, puedes pagar desde aqui: {payment_url}"
        return answer
    return None


def _extract_widget_add_to_cart(message: str) -> dict[str, Any] | None:
    requests = _extract_widget_cart_requests(message)
    return requests[0] if requests else None


def _extract_widget_remove_from_cart(message: str) -> dict[str, Any] | None:
    requests = _extract_widget_cart_change_requests(message, mode="remove")
    return requests[0] if requests else None


def _extract_widget_set_cart_quantity(message: str) -> dict[str, Any] | None:
    requests = _extract_widget_cart_change_requests(message, mode="set")
    return requests[0] if requests else None


def _resolve_cart_request_for_intent(
    *,
    user_message: str,
    intent: str,
    session_id: str | None,
) -> dict[str, Any] | None:
    normalized_intent = (intent or "").strip().lower()
    if normalized_intent == "add_to_cart":
        explicit = _extract_widget_add_to_cart(user_message)
        if explicit:
            return explicit
    if normalized_intent == "remove_from_cart":
        explicit = _extract_widget_remove_from_cart(user_message)
        if explicit:
            return explicit
    if normalized_intent == "set_cart_quantity":
        explicit = _extract_widget_set_cart_quantity(user_message)
        if explicit:
            return explicit
    return None


def _format_public_widget_tool_payload(
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
            products.append(_normalize_catalog_product(item))

        cart_request = _resolve_cart_request_for_intent(
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

        remove_request = _resolve_cart_request_for_intent(
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

        set_quantity_request = _resolve_cart_request_for_intent(
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
                "workflow_stage": "product_lookup",
                "pending_next_step": "add_to_cart",
            }

        formatted = "\n".join(f"• {p['name']} — ${p['price']}" for p in products[:5] if p.get('name'))
        return {
            "answer": f"Te paso las opciones que tengo:\n{formatted}" if formatted else "No encontre productos.",
            "products": products,
            "workflow_stage": "product_lookup",
            "pending_next_step": "add_to_cart",
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
        order_reference = _first_present_string(data, ["order_reference", "order_id", "id", "number"])
        status = _first_present_string(data, ["status", "order_status", "state"])
        tracking_url = _first_present_string(data, ["tracking_url", "tracking_link"])
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
        payment_url = _first_present_string(data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
        expires_at = _first_present_string(data, ["expires_at", "expiration", "expires_on"])
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
        draft_reference = _first_present_string(data, ["draft_id", "order_id", "order_reference", "id", "number"])
        payment_url = _first_present_string(data, ["payment_url", "payment_link", "checkout_url", "url", "link"])
        total = _first_present_string(data, ["total", "amount", "grand_total"])
        answer = (
            f"Listo, deje creada la orden borrador {draft_reference}." if draft_reference else "Listo, deje creada la orden borrador."
        )
        if total:
            answer += f" Total referencial: {total}."
        if payment_url:
            answer += " Si quieres, ya puedes pasar al pago."
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

    tool_answer = _format_canonical_tool_answer(result)
    if not tool_answer:
        return None
    return {"answer": tool_answer}


def _build_multi_cart_tool_payload(
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
        "cart_action": cart_actions[0],
        "cart_actions": cart_actions,
        "products": products[:6],
        "workflow_stage": "cart_building",
        "pending_next_step": "shipping_selection",
    }


def _build_multi_product_lookup_payload(
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
            normalized_product = _normalize_catalog_product(item)
            normalized_product["query"] = query
            products.append(normalized_product)

    if not products:
        return None

    normalized_message = _normalize_widget_text(user_message)
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
        "workflow_stage": "product_lookup",
        "pending_next_step": "cart_building",
    }


def _build_recipe_recommendation_payload(
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
                products.append(_normalize_catalog_product(item))

        if available_names:
            recipe_lines.append(f"- {recipe_name}: {reason or 'Te puede servir'} Ingredientes sugeridos: {', '.join(available_names[:5])}.")

    if not recipe_lines:
        return None

    return {
        "answer": "Te recomiendo estas recetas con productos que podrias llevar:\n" + "\n".join(recipe_lines),
        "products": products[:6],
    }


def _resolve_shared_commerce_payload(
    *,
    company_id: str,
    user_id: str,
    session_id: str,
    message: str,
    channel: str,
    clubhx_tools_client: ClubHxToolsClient | None,
    intent_label: str | None = None,
    response_style_context: str | None = None,
    workflow_state: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if clubhx_tools_client is None:
        _trace_route(
            "commerce.skip_no_tools_client",
            session_id=session_id,
            channel=channel,
            message=message,
        )
        logger.warning(
            "commerce_router_skip reason=no_tools_client session_id=%s channel=%s message=%s",
            session_id,
            channel,
            message,
        )
        return None

    normalized_message = _normalize_widget_text(message)
    _trace_route(
        "commerce.start",
        session_id=session_id,
        channel=channel,
        message=normalized_message,
        greeting_like=_is_likely_greeting_message(message),
        workflow_stage=str((workflow_state or {}).get("stage") or ""),
        checkout_stage=str((workflow_state or {}).get("checkout_stage") or ""),
        pending_next_step=str((workflow_state or {}).get("pending_next_step") or ""),
    )
    logger.warning(
        "commerce_router_start session_id=%s channel=%s greeting_like=%s message=%s workflow_stage=%s checkout_stage=%s pending_next_step=%s",
        session_id,
        channel,
        _is_likely_greeting_message(message),
        normalized_message,
        str((workflow_state or {}).get("stage") or ""),
        str((workflow_state or {}).get("checkout_stage") or ""),
        str((workflow_state or {}).get("pending_next_step") or ""),
    )

    llm_commerce_intent = _parse_commerce_intent_with_openai(
        message,
        session_id=session_id,
        intent_label=intent_label,
        channel=channel,
        response_style_context=response_style_context,
        workflow_context=(
            f"stage={str((workflow_state or {}).get('stage') or '')};"
            f"checkout_stage={str((workflow_state or {}).get('checkout_stage') or '')};"
            f"pending_next_step={str((workflow_state or {}).get('pending_next_step') or '')};"
            f"otp_email={str((workflow_state or {}).get('otp_email') or '')}"
        ),
    )

    current_invoice_data = _extract_invoice_data(message, session_id=session_id)
    current_workflow = build_workflow_state(
        stage=(workflow_state or {}).get("stage"),
        checkout_stage=(workflow_state or {}).get("checkout_stage"),
        selected_products=(workflow_state or {}).get("selected_products"),
        shipping_preference=(workflow_state or {}).get("shipping_preference") or (message if any(token in _normalize_widget_text(message) for token in ["envio", "despacho", "retiro", "comuna"]) else ""),
        pickup_location_label=(workflow_state or {}).get("pickup_location_label") or _extract_pickup_location(message),
        delivery_address=(workflow_state or {}).get("delivery_address") or _extract_address(message),
        delivery_address_confirmed=_workflow_state_bool((workflow_state or {}).get("delivery_address_confirmed")),
        invoice_type=(workflow_state or {}).get("invoice_type") or current_invoice_data.get("invoice_type"),
        invoice_rut=(workflow_state or {}).get("invoice_rut") or current_invoice_data.get("rut"),
        invoice_business_name=(workflow_state or {}).get("invoice_business_name") or current_invoice_data.get("business_name"),
        invoice_address=(workflow_state or {}).get("invoice_address") or current_invoice_data.get("invoice_address"),
        payment_preference=(workflow_state or {}).get("payment_preference") or (message if any(token in _normalize_widget_text(message) for token in ["pago", "tarjeta", "transferencia", "link de pago"]) else ""),
        customer_authenticated=_workflow_state_customer_authenticated(workflow_state) or _is_login_confirmed_message(message),
        order_reference=(workflow_state or {}).get("order_reference") or "",
    )

    followup_payload = _resolve_affirmative_workflow_followup(
        message=message,
        workflow_state=workflow_state,
    )
    if followup_payload:
        _trace_route(
            "commerce.resolve_affirmative_followup",
            session_id=session_id,
            intent=str(followup_payload.get("intent_label") or ""),
            workflow_stage=str(followup_payload.get("workflow_stage") or ""),
        )
        logger.warning(
            "commerce_router_resolved kind=affirmative_followup session_id=%s payload_intent=%s workflow_stage=%s pending_next_step=%s",
            session_id,
            str(followup_payload.get("intent_label") or ""),
            str(followup_payload.get("workflow_stage") or ""),
            str(followup_payload.get("pending_next_step") or ""),
        )
        return followup_payload

    checkout_followup_payload = _resolve_checkout_workflow_followup(
        message=message,
        session_id=session_id,
        workflow_state=workflow_state,
        company_id=company_id,
        channel=channel,
        user_id=user_id,
        clubhx_tools_client=clubhx_tools_client,
    )
    if checkout_followup_payload:
        _trace_route(
            "commerce.resolve_checkout_followup",
            session_id=session_id,
            intent=str(checkout_followup_payload.get("intent_label") or ""),
            workflow_stage=str(checkout_followup_payload.get("workflow_stage") or ""),
            checkout_stage=str(checkout_followup_payload.get("checkout_stage") or ""),
        )
        logger.warning(
            "commerce_router_resolved kind=checkout_followup session_id=%s payload_intent=%s workflow_stage=%s checkout_stage=%s",
            session_id,
            str(checkout_followup_payload.get("intent_label") or ""),
            str(checkout_followup_payload.get("workflow_stage") or ""),
            str(checkout_followup_payload.get("checkout_stage") or ""),
        )
        return checkout_followup_payload

    if _is_clear_cart_message(message):
        _trace_route("commerce.resolve_clear_cart", session_id=session_id)
        logger.warning(
            "commerce_router_resolved kind=clear_cart session_id=%s",
            session_id,
        )
        return {
            "answer": "Listo, vacie el carrito.",
            "intent_label": "clear_cart",
            "workflow_stage": "browsing",
            "pending_next_step": "",
            "cart_action": {"type": "clear_cart"},
        }

    if str((llm_commerce_intent or {}).get("intent") or "").strip().lower() == "cart_status":
        _trace_route("commerce.resolve_cart_status", session_id=session_id)
        recent = _recent_commerce_products(session_id)
        if recent:
            lines = [f"• {p.get('name', 'Producto')} — ${p.get('price', '?')}" for p in recent[:5]]
            answer = "Resumen de tu carrito:\n" + "\n".join(lines)
        else:
            answer = "Tu carrito esta vacio. Decime que producto queres llevar y te lo agrego."
        return {
            "answer": answer,
            "intent_label": "cart_status",
            "workflow_stage": str((workflow_state or {}).get("stage") or "cart_building") or "cart_building",
            "pending_next_step": str((workflow_state or {}).get("pending_next_step") or "cart_building"),
            "workflow_action": _workflow_action("show_cart"),
        }

    if isinstance(llm_commerce_intent, dict):
        _trace_route(
            "commerce.llm_intent",
            session_id=session_id,
            intent=str(llm_commerce_intent.get("intent") or ""),
            tool=str(llm_commerce_intent.get("tool") or ""),
            query=str(llm_commerce_intent.get("query") or ""),
            needs_clarification=bool(llm_commerce_intent.get("needs_clarification")),
        )
        logger.warning(
            "commerce_router_llm_intent session_id=%s intent=%s tool=%s needs_clarification=%s query=%s",
            session_id,
            str(llm_commerce_intent.get("intent") or ""),
            str(llm_commerce_intent.get("tool") or ""),
            bool(llm_commerce_intent.get("needs_clarification")),
            str(llm_commerce_intent.get("query") or ""),
        )

        llm_intent_name = str(llm_commerce_intent.get("intent") or "").strip().lower()
        llm_tool_name = str(llm_commerce_intent.get("tool") or "").strip().lower()
        if _is_checkout_redirect_channel(channel) and (
            llm_intent_name in {"create_payment_link", "payment_options"}
            or llm_tool_name in {"create_payment_link", "get_payment_options"}
            or _is_checkout_request_message(message)
        ):
            _trace_route(
                "commerce.resolve_web_checkout_redirect",
                session_id=session_id,
                intent=llm_intent_name,
                tool=llm_tool_name,
            )
            return {
                "answer": "Te llevo al checkout para revisar tu carrito, despacho y pago.",
                "intent_label": llm_intent_name or "checkout_web",
                "workflow_stage": "checkout_ready",
                "checkout_stage": "web_checkout_redirect",
                "pending_next_step": "payment_selection",
                "redirect_to": "/cart",
                "workflow_action": _workflow_action(
                    "open_checkout",
                    redirect_to="/cart",
                ),
            }

        if bool(llm_commerce_intent.get("needs_clarification")):
            clarification = str(llm_commerce_intent.get("clarification_question") or "").strip()
            if clarification:
                _trace_route(
                    "commerce.resolve_clarification",
                    session_id=session_id,
                    intent=str(llm_commerce_intent.get("intent") or ""),
                    clarification=clarification,
                )
                logger.warning(
                    "commerce_router_resolved kind=clarification session_id=%s intent=%s question=%s",
                    session_id,
                    str(llm_commerce_intent.get("intent") or ""),
                    clarification,
                )
                return {"answer": clarification}

        planned_tool = _tool_from_llm_commerce_intent(llm_commerce_intent, session_id)
        if planned_tool is None and llm_intent_name in {"create_payment_link", "create_order_draft", "checkout"}:
            planned_tool = (llm_intent_name, {"session_id": session_id})
        transition = resolve_workflow_transition(
            current=current_workflow,
            intent_label=str(llm_commerce_intent.get("intent") or intent_label or ""),
            tool_name=planned_tool[0] if planned_tool else None,
        )
        if not transition.allowed and transition.clarification:
            _trace_route(
                "commerce.blocked",
                session_id=session_id,
                intent=str(llm_commerce_intent.get("intent") or ""),
                tool=planned_tool[0] if planned_tool else "",
                clarification=transition.clarification,
            )
            logger.warning(
                "commerce_router_blocked session_id=%s intent=%s tool=%s clarification=%s",
                session_id,
                str(llm_commerce_intent.get("intent") or ""),
                planned_tool[0] if planned_tool else "",
                transition.clarification,
            )
            return {
                "answer": transition.clarification,
                "intent_label": str(llm_commerce_intent.get("intent") or intent_label or "commerce").strip() or "commerce",
            }
        if planned_tool and planned_tool[0] in {"get_order_status", "get_shipping_options", "get_payment_options", "get_product_availability"}:
            _trace_route(
                "commerce.tool_call",
                session_id=session_id,
                tool=planned_tool[0],
                arguments=planned_tool[1],
            )
            logger.warning(
                "commerce_router_tool_call session_id=%s tool=%s arguments=%s",
                session_id,
                planned_tool[0],
                planned_tool[1],
            )
            canonical = clubhx_tools_client.execute_canonical(
                tenant_id=company_id,
                tool=planned_tool[0],
                channel=channel,
                user_id=user_id,
                arguments=planned_tool[1],
            )
            payload = _format_public_widget_tool_payload(
                canonical,
                user_message=message,
                intent_label=str(llm_commerce_intent.get("intent") or intent_label or ""),
                channel=channel,
                session_id=session_id,
            )
            if payload:
                _trace_route(
                    "commerce.resolve_tool_payload",
                    session_id=session_id,
                    tool=planned_tool[0],
                    intent=str(payload.get("intent_label") or llm_commerce_intent.get("intent") or ""),
                    workflow_stage=str(payload.get("workflow_stage") or transition.next_stage),
                )
                logger.warning(
                    "commerce_router_resolved kind=tool_payload session_id=%s tool=%s payload_intent=%s workflow_stage=%s",
                    session_id,
                    planned_tool[0],
                    str(payload.get("intent_label") or llm_commerce_intent.get("intent") or ""),
                    str(payload.get("workflow_stage") or transition.next_stage),
                )
                payload.setdefault("intent_label", str(llm_commerce_intent.get("intent") or "commerce").strip() or "commerce")
                payload.setdefault("workflow_stage", transition.next_stage)
                return payload

        if planned_tool and planned_tool[0] in {"create_order_draft", "create_payment_link"}:
            _trace_route(
                "commerce.checkout_tool",
                session_id=session_id,
                tool=planned_tool[0],
            )
            logger.warning(
                "commerce_router_checkout_tool session_id=%s tool=%s",
                session_id,
                planned_tool[0],
            )
            cart_requests = _checkout_requests_for_workflow(message, session_id, llm_commerce_intent)
            if not cart_requests:
                if _is_checkout_redirect_channel(channel):
                    return {
                        "answer": "Te llevo al checkout para revisar tu carrito, despacho y pago.",
                        "intent_label": str(llm_commerce_intent.get("intent") or intent_label or "checkout_web").strip() or "checkout_web",
                        "workflow_stage": "checkout_ready",
                        "checkout_stage": "web_checkout_redirect",
                        "pending_next_step": "payment_selection",
                        "redirect_to": "/cart",
                        "workflow_action": _workflow_action(
                            "open_checkout",
                            redirect_to="/cart",
                        ),
                    }
                recent = _recent_commerce_products(session_id)
                if recent:
                    cart_requests = [
                        {"product_query": p.get("name", ""), "quantity": 1}
                        for p in recent[:3] if p.get("name")
                    ]
                    logger.warning(
                        "commerce_checkout_recent_fallback session_id=%s cart_requests=%s",
                        session_id, cart_requests,
                    )
                if not cart_requests:
                    return {
                        "answer": "Primero decime que producto queres llevar y te ayudo con el pago.",
                        "intent_label": str(llm_commerce_intent.get("intent") or intent_label or "commerce").strip() or "commerce",
                    }
            if not _is_checkout_redirect_channel(channel):
                if not current_workflow.customer_authenticated:
                    if _is_email_message(message):
                        send_ok = False
                        if clubhx_tools_client is not None:
                            try:
                                result = clubhx_tools_client.execute_canonical(
                                    tenant_id=company_id,
                                    tool="send_verification_code",
                                    channel=channel,
                                    user_id=user_id,
                                    arguments={"email": message.strip()},
                                )
                                logger.info(
                                    "send_verification_code_ok session_id=%s email=%s result=%s",
                                    session_id, message.strip(), result,
                                )
                                send_ok = _canonical_tool_succeeded(result, expected_statuses={"sent", "ok", "success"})
                            except Exception as exc:
                                logger.warning("send_verification_code_failed session_id=%s email=%s detail=%s", session_id, message.strip(), exc)
                        if not send_ok:
                            return {
                                "answer": "No pude enviar el código de verificación. Probá de nuevo con tu correo.",
                                "intent_label": "checkout_otp_send_failed",
                                "workflow_stage": "checkout_ready",
                                "checkout_stage": "auth_pending",
                                "pending_next_step": "auth_confirmation",
                                "workflow_action": _workflow_action("otp_send_failed"),
                            }
                        return {
                            "answer": f"Te enviamos un codigo de verificacion a {message.strip()}. Ingresalo aca para continuar.",
                            "intent_label": "checkout_otp_sent",
                            "workflow_stage": "checkout_ready",
                            "checkout_stage": "otp_pending",
                            "pending_next_step": "otp_verification",
                            "otp_email": message.strip(),
                            "workflow_action": _workflow_action("otp_sent"),
                        }
                    return {
                        "answer": "Para seguir con el pago necesito que inicies sesion primero. Escribe tu correo electronico para enviarte un codigo de verificacion.",
                        "intent_label": "checkout_auth_needed",
                        "workflow_stage": "checkout_ready",
                        "checkout_stage": "auth_pending",
                        "pending_next_step": "auth_confirmation",
                        "workflow_action": _workflow_action("request_auth"),
                    }
                shipping_ready = (
                    current_workflow.has_pickup_location
                    or (current_workflow.has_delivery_address and current_workflow.delivery_address_confirmed)
                )
                if not shipping_ready:
                    existing_address = str((workflow_state or {}).get("delivery_address") or "").strip()
                    if existing_address and not _workflow_state_bool((workflow_state or {}).get("delivery_address_confirmed")):
                        return {
                            "answer": f"Encontre esta direccion de despacho:\n{existing_address}\n\nEsta correcta?",
                            "intent_label": "delivery_address_confirmation_pending",
                            "workflow_stage": "shipping_selection",
                            "checkout_stage": "delivery_address_proposed",
                            "pending_next_step": "delivery_address_confirmation",
                            "workflow_action": _workflow_action("request_address_confirmation"),
                        }
                    return {
                        "answer": "Ahora necesito saber si preferis retiro en tienda o despacho a domicilio.",
                        "intent_label": "shipping_options",
                        "workflow_stage": "shipping_selection",
                        "checkout_stage": "shipping_method_pending",
                        "pending_next_step": "shipping_selection",
                        "workflow_action": _workflow_action("choose_shipping_method"),
                    }
                invoice_ready = not current_workflow.has_invoice_type or current_workflow.invoice_data_complete
                if not invoice_ready:
                    return {
                        "answer": "Antes de generar el pago, necesito saber si quieres boleta o factura.",
                        "intent_label": "invoice_type_pending",
                        "workflow_stage": "payment_selection",
                        "checkout_stage": "invoice_type_pending",
                        "pending_next_step": "invoice_type",
                        "workflow_action": _workflow_action("request_invoice_type"),
                    }
            checkout_items, checkout_products = _resolve_checkout_items(
                company_id=company_id,
                user_id=user_id,
                channel=channel,
                session_id=session_id,
                cart_requests=cart_requests,
                clubhx_tools_client=clubhx_tools_client,
            )
            if not checkout_items:
                return {"answer": "No pude validar los productos del pedido. Si quieres, dime el nombre exacto del producto y la cantidad."}
            canonical = clubhx_tools_client.execute_canonical(
                tenant_id=company_id,
                tool=planned_tool[0],
                channel=channel,
                user_id=user_id,
                arguments={
                    **planned_tool[1],
                    "items": checkout_items,
                    "session_id": session_id,
                },
            )
            payload = _format_public_widget_tool_payload(
                canonical,
                user_message=message,
                intent_label=str(llm_commerce_intent.get("intent") or intent_label or ""),
                channel=channel,
                session_id=session_id,
            )
            if payload:
                _trace_route(
                    "commerce.resolve_checkout_payload",
                    session_id=session_id,
                    tool=planned_tool[0],
                    checkout_stage=str(payload.get("checkout_stage") or ""),
                    reset=bool(payload.get("reset_workflow")),
                )
                logger.warning(
                    "commerce_router_resolved kind=checkout_payload session_id=%s tool=%s checkout_stage=%s reset=%s",
                    session_id,
                    planned_tool[0],
                    str(payload.get("checkout_stage") or ""),
                    bool(payload.get("reset_workflow")),
                )
                if checkout_products and not payload.get("products"):
                    payload["products"] = checkout_products[:6]
                payload.setdefault("intent_label", str(llm_commerce_intent.get("intent") or "commerce").strip() or "commerce")
                payload.setdefault("workflow_stage", transition.next_stage)
                return payload

    if str((llm_commerce_intent or {}).get("intent") or "").strip().lower() == "recipe_recommendation":
        recipe_plan = _generate_recipe_plan_with_openai(message, session_id, _recent_commerce_products(session_id))
        if isinstance(recipe_plan, dict):
            ingredient_queries: list[str] = []
            seen_queries: set[str] = set()
            for recipe in recipe_plan.get("recipes") if isinstance(recipe_plan.get("recipes"), list) else []:
                if not isinstance(recipe, dict):
                    continue
                for ingredient_query in recipe.get("ingredient_queries") if isinstance(recipe.get("ingredient_queries"), list) else []:
                    clean_query = str(ingredient_query).strip()
                    if clean_query and clean_query not in seen_queries:
                        seen_queries.add(clean_query)
                        ingredient_queries.append(clean_query)
            ingredient_results_by_query = {
                query: clubhx_tools_client.execute_canonical(
                    tenant_id=company_id,
                    tool="get_product_availability",
                    channel=channel,
                    user_id=user_id,
                    arguments={
                        "query": query,
                        "limit": 3,
                        "session_id": session_id,
                    },
                )
                for query in ingredient_queries[:8]
            }
            payload = _build_recipe_recommendation_payload(recipe_plan, ingredient_results_by_query)
            if payload:
                return payload

    cart_requests = _cart_requests_from_llm_intent(llm_commerce_intent)
    if cart_requests:
        _trace_route("commerce.cart_requests", session_id=session_id, requests=cart_requests)
        logger.warning(
            "commerce_router_cart_requests session_id=%s requests=%s",
            session_id,
            cart_requests,
        )
        canonical_results = [
            clubhx_tools_client.execute_canonical(
                tenant_id=company_id,
                tool="get_product_availability",
                channel=channel,
                user_id=user_id,
                arguments={
                    "query": str(cart_request.get("product_query") or "").strip(),
                    "limit": 5,
                    "session_id": session_id,
                },
            )
            for cart_request in cart_requests
        ]
        payload = _build_multi_cart_tool_payload(canonical_results, cart_requests)
        if payload:
            _trace_route(
                "commerce.resolve_multi_cart_payload",
                session_id=session_id,
                workflow_stage=str(payload.get("workflow_stage") or ""),
            )
            logger.warning(
                "commerce_router_resolved kind=multi_cart_payload session_id=%s workflow_stage=%s",
                session_id,
                str(payload.get("workflow_stage") or ""),
            )
            return payload

    lookup_queries = _product_lookup_queries_from_llm_intent(llm_commerce_intent)
    if len(lookup_queries) > 1:
        _trace_route("commerce.lookup_queries", session_id=session_id, queries=lookup_queries)
        logger.warning(
            "commerce_router_lookup_queries session_id=%s queries=%s",
            session_id,
            lookup_queries,
        )
        canonical_results = [
            clubhx_tools_client.execute_canonical(
                tenant_id=company_id,
                tool="get_product_availability",
                channel=channel,
                user_id=user_id,
                arguments={
                    "query": query,
                    "limit": 3,
                    "session_id": session_id,
                },
            )
            for query in lookup_queries
        ]
        payload = _build_multi_product_lookup_payload(canonical_results, lookup_queries, message, channel=channel)
        if payload:
            _trace_route(
                "commerce.resolve_multi_lookup_payload",
                session_id=session_id,
                products=len(payload.get("products") or []),
            )
            logger.warning(
                "commerce_router_resolved kind=multi_lookup_payload session_id=%s products=%s",
                session_id,
                len(payload.get("products") or []),
            )
            return payload

    _trace_route(
        "commerce.no_payload",
        session_id=session_id,
        greeting_like=_is_likely_greeting_message(message),
        normalized_message=normalized_message,
        llm_intent=str((llm_commerce_intent or {}).get("intent") or ""),
        lookup_queries=lookup_queries if 'lookup_queries' in locals() else [],
    )
    logger.warning(
        "commerce_router_no_payload session_id=%s greeting_like=%s normalized_message=%s llm_intent=%s lookup_queries=%s",
        session_id,
        _is_likely_greeting_message(message),
        normalized_message,
        str((llm_commerce_intent or {}).get("intent") or ""),
        lookup_queries if 'lookup_queries' in locals() else [],
    )
    return None


_PUBLIC_WIDGET_RATE_LOCK = threading.Lock()
_PUBLIC_WIDGET_RATE_EVENTS: dict[str, list[float]] = {}


def _configure_agent_usage_logging() -> None:
    raw_path = os.getenv("AGENT_USAGE_LOG_PATH", "logs/agent_usage.log").strip()
    if not raw_path:
        return

    log_path = Path(raw_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    resolved = str(log_path.resolve())
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    for name in (__name__, "clasificacion_langchain.agents.service"):
        target_logger = logging.getLogger(name)
        target_logger.setLevel(logging.INFO)

        already_configured = False
        for handler in target_logger.handlers:
            if not isinstance(handler, logging.FileHandler):
                continue
            if getattr(handler, "baseFilename", "") == resolved:
                already_configured = True
                break

        if already_configured:
            continue

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        target_logger.addHandler(file_handler)


_configure_agent_usage_logging()

_clubhx_tools_client: ClubHxToolsClient | None = None
_clubhx_tools_signature: tuple[str, str, int] | None = None


def _get_clubhx_tools_client() -> ClubHxToolsClient | None:
    global _clubhx_tools_client, _clubhx_tools_signature

    base_url = os.getenv("CLUBHX_API_BASE_URL", "").strip()
    service_token = os.getenv("CLUBHX_SERVICE_TOKEN", "").strip()
    shop_domain = (
        os.getenv("CLUBHX_SHOP_DOMAIN", "").strip()
        or os.getenv("SHOP_DOMAIN", "").strip()
    )
    timeout_seconds = int(os.getenv("CLUBHX_TOOLS_TIMEOUT_SECONDS", "12") or "12")

    if not base_url or not service_token:
        logger.warning(
            "clubhx_tools_client_unavailable base_url_present=%s token_present=%s",
            bool(base_url),
            bool(service_token),
        )
        _clubhx_tools_client = None
        _clubhx_tools_signature = None
        return None

    signature = (base_url, service_token, shop_domain, timeout_seconds)
    if _clubhx_tools_client is None or _clubhx_tools_signature != signature:
        logger.info(
            "clubhx_tools_client_init base_url=%s shop_domain=%s timeout_seconds=%s",
            base_url,
            shop_domain,
            timeout_seconds,
        )
        _clubhx_tools_client = ClubHxToolsClient(
            base_url=base_url,
            service_token=service_token,
            shop_domain=shop_domain or None,
            timeout_seconds=timeout_seconds,
        )
        _clubhx_tools_signature = signature

    return _clubhx_tools_client


class ChatRequestPayload(BaseModel):
    company_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    message: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)
    generation_provider: str | None = Field(default=None)
    generation_model: str | None = Field(default=None)
    use_openai_generation: bool | None = Field(default=None)


class AgentCreatePayload(BaseModel):
    name: str = Field(min_length=2)
    objective: str = Field(default="Responder consultas de la empresa", min_length=8)
    tone: str = Field(default="profesional", min_length=3)
    description: str = ""
    company_id: str | None = Field(default=None, min_length=1)
    rag_backend: str = Field(default="auto")
    generation_provider: str = Field(default="auto")
    use_openai_generation: bool = False
    openai_model: str | None = Field(default=None, min_length=3)


class AgentUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=2)
    objective: str | None = Field(default=None, min_length=8)
    tone: str | None = Field(default=None, min_length=3)
    description: str | None = None
    rag_backend: str | None = None
    generation_provider: str | None = None
    use_openai_generation: bool | None = None
    openai_model: str | None = Field(default=None, min_length=3)


class AgentPayload(BaseModel):
    agent_id: str
    org_id: str
    company_id: str
    name: str
    objective: str
    tone: str
    description: str
    rag_backend: str
    generation_provider: str
    use_openai_generation: bool
    openai_model: str
    knowledge_dir: str
    index_path: str
    indexed_at: str | None
    documents_count: int


class AgentDocumentPayload(BaseModel):
    document_id: str
    agent_id: str
    filename: str
    size_bytes: int
    status: str
    indexed_at: str | None
    error_message: str | None
    created_at: str
    operational_section: str | None = None
    learning_summary: str | None = None
    summary_updated_at: str | None = None


class AgentDocumentContentPayload(BaseModel):
    document_id: str
    agent_id: str
    filename: str
    status: str
    created_at: str
    content: str


class AgentWebAnalysisRequestPayload(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    timeout_seconds: int = Field(default=15, ge=3, le=60)
    max_chars: int = Field(default=18000, ge=500, le=120000)
    max_points: int = Field(default=5, ge=1, le=12)


class AgentWebAnalysisPayload(BaseModel):
    url: str
    status_code: int
    title: str
    content_excerpt: str
    key_points: list[str]
    word_count: int


class AgentIndexStatusPayload(BaseModel):
    agent_id: str
    has_index: bool
    indexed_at: str | None
    documents_total: int
    documents_indexed: int
    documents_failed: int
    documents_uploaded: int
    last_error: str | None


class AgentIndexPayload(BaseModel):
    agent_id: str
    backend: str
    total_documents: int
    total_chunks: int
    companies: list[str]
    index_path: str


class AgentChatRequestPayload(BaseModel):
    message: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)
    session_id: str | None = Field(default=None, min_length=1)
    channel: str | None = Field(default=None, min_length=1)
    use_openai_generation: bool | None = None
    generation_provider: str | None = None
    generation_model: str | None = Field(default=None, min_length=3)


class InternalAgentDocumentUploadPayload(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=4)
    operational_section: str | None = None


class TenantLlmSettingsUpdatePayload(BaseModel):
    company_id: str | None = Field(default=None, min_length=1)
    generation_provider: str | None = None
    openai_model: str | None = Field(default=None, min_length=3)
    anthropic_model: str | None = Field(default=None, min_length=3)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    clear_openai_api_key: bool = False
    clear_anthropic_api_key: bool = False


class TenantLlmSettingsPayload(BaseModel):
    company_id: str
    generation_provider: str
    openai_model: str
    anthropic_model: str
    has_openai_api_key: bool
    has_anthropic_api_key: bool
    openai_api_key_masked: str | None
    anthropic_api_key_masked: str | None
    openai_key_source: str
    anthropic_key_source: str
    updated_at: str


class AgentChatResponsePayload(BaseModel):
    agent_id: str
    company_id: str
    session_id: str
    answer: str
    sources: list[str]
    intent_label: str | None = None
    route: str | None = None
    route_reason: str | None = None
    response_mode: str | None = None
    fallback_applied: bool = False
    retrieval_min_score: float | None = None
    redirect_to: str | None = None
    workflow_action: dict[str, Any] | None = None
    cart_action: dict[str, Any] | None = None
    cart_actions: list[dict[str, Any]] | None = None
    products: list[dict[str, Any]] | None = None


class InternalRuntimeExecuteRequestPayload(BaseModel):
    version: int = Field(ge=1)
    input: dict[str, Any] | None = None


class InternalRuntimeExecuteResponsePayload(BaseModel):
    execution_id: str
    type: str
    id: str
    version: int
    status: str
    output: dict[str, Any]


class AgentWidgetConfigPayload(BaseModel):
    agent_id: str
    widget_id: str
    endpoint_url: str
    widget_token: str
    allowed_origins: list[str]
    rate_limit_window_seconds: int
    rate_limit_max_requests: int
    snippet_html: str


class AgentWhatsAppConfigPayload(BaseModel):
    agent_id: str
    company_id: str
    webhook_url: str
    phone_number_id: str | None = None
    business_account_id: str | None = None
    verify_token: str | None = None
    updated_at: str | None = None


class AgentWhatsAppConfigUpdatePayload(BaseModel):
    phone_number_id: str | None = None
    business_account_id: str | None = None
    verify_token: str | None = None


class AgentWhatsAppValidationPayload(BaseModel):
    agent_id: str
    company_id: str
    ready: bool
    has_phone_number_id: bool
    has_verify_token: bool
    server_has_access_token: bool
    company_map_ready: bool
    webhook_url: str
    messages: list[str]


def _is_agent_whatsapp_config_ready(config: dict[str, str | None]) -> bool:
    return bool((config.get("phone_number_id") or "").strip()) and bool(
        (config.get("verify_token") or "").strip()
    )


class AgentSetupStepPayload(BaseModel):
    id: str
    label: str
    description: str
    ready: bool
    href: str


class AgentSetupStatusPayload(BaseModel):
    agent_id: str
    company_id: str
    agent_name: str
    rag_backend: str
    progress_percent: int
    ready_to_publish: bool
    next_href: str | None
    documents_total: int
    documents_indexed: int
    test_messages: int
    steps: list[AgentSetupStepPayload]


class PublicWidgetChatRequestPayload(BaseModel):
    widget_id: str = Field(min_length=1)
    widget_token: str = Field(min_length=8)
    message: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    visitor_id: str | None = Field(default=None, min_length=1)
    external_user_id: str | None = Field(default=None, min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)


class PublicWidgetChatResponsePayload(BaseModel):
    widget_id: str
    session_id: str
    answer: str
    sources: list[str]
    route: str | None = None
    intent_label: str | None = None
    response_mode: str | None = None
    redirect_to: str | None = None
    workflow_action: dict[str, Any] | None = None
    cart_action: dict[str, Any] | None = None
    cart_actions: list[dict[str, Any]] | None = None
    products: list[dict[str, Any]] | None = None


class MediaTranscriptionPayload(BaseModel):
    text: str
    language: str | None = None
    confidence: float | None = None
    duration_ms: int | None = None
    provider: str | None = None


class MediaTranscriptionRequestPayload(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=4)
    mime_type: str | None = None
    language_hint: str | None = None
    channel: str | None = None
    source: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    phone_number_id: str | None = None


class ChatAuditSummaryRowPayload(BaseModel):
    company_id: str
    agent_id: str
    assistant_messages: int
    cached_responses: int
    generic_repeat_responses: int
    closed_conversations: int


class ChatAuditCostRowPayload(BaseModel):
    company_id: str
    agent_id: str
    assistant_messages: int
    llm_messages: int
    avoided_llm_calls: int
    estimated_spent_usd: float
    estimated_saved_usd: float


class RetrievalAuditSummaryRowPayload(BaseModel):
    company_id: str
    agent_id: str
    queries_total: int
    answers_with_sources: int
    answers_without_sources: int
    fallback_count: int
    avg_retrieved_chunks: float
    avg_retrieval_score: float
    avg_latency_ms: float


class RetrievalBackendMetricsPayload(BaseModel):
    backend: str
    queries_total: int
    answers_with_sources: int
    fallback_count: int
    avg_retrieval_score: float
    avg_latency_ms: float


class RetrievalComparisonPayload(BaseModel):
    company_id: str
    agent_id: str
    current_backend: str
    baseline_backend: str | None
    current: RetrievalBackendMetricsPayload
    baseline: RetrievalBackendMetricsPayload | None
    grounded_rate_delta: float | None
    fallback_rate_delta: float | None
    score_delta: float | None
    latency_delta_ms: float | None


class RagDecisionCreatePayload(BaseModel):
    decision: str = Field(min_length=2, max_length=80)
    current_backend: str = Field(min_length=2, max_length=32)
    baseline_backend: str | None = Field(default=None, min_length=2, max_length=32)
    reason: str = Field(min_length=6, max_length=800)
    grounded_rate_delta: float | None = None
    fallback_rate_delta: float | None = None
    score_delta: float | None = None
    latency_delta_ms: float | None = None


class RagDecisionRecordPayload(BaseModel):
    recorded_at: str
    agent_id: str
    company_id: str
    decision: str
    current_backend: str
    baseline_backend: str | None
    reason: str
    grounded_rate_delta: float | None
    fallback_rate_delta: float | None
    score_delta: float | None
    latency_delta_ms: float | None


class EvaluationCasePayload(BaseModel):
    question: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)


class EvaluationDatasetPayload(BaseModel):
    cases: list[EvaluationCasePayload] = Field(default_factory=list)


class EvaluationRunPayload(BaseModel):
    run_id: str
    recorded_at: str
    agent_id: str
    company_id: str
    rag_backend: str
    cases_total: int
    accuracy: float
    semantic_accuracy: float | None
    grounded_rate: float
    fallback_rate: float
    avg_case_score: float
    semantic_score_avg: float | None
    avg_latency_ms: float
    llm_judge_enabled: bool
    llm_judge_scored_cases: int


class EvaluationRunRequestPayload(BaseModel):
    sample_size: int | None = Field(default=None, ge=1, le=500)


class EvaluationRunJobPayload(BaseModel):
    job_id: str
    agent_id: str
    company_id: str
    status: str
    sample_size: int | None
    created_at: str
    updated_at: str
    error: str | None = None
    run: EvaluationRunPayload | None = None


class EvaluationComparePayload(BaseModel):
    agent_id: str
    company_id: str
    current: EvaluationRunPayload | None
    baseline: EvaluationRunPayload | None
    accuracy_delta: float | None
    semantic_accuracy_delta: float | None
    grounded_rate_delta: float | None
    fallback_rate_delta: float | None
    avg_case_score_delta: float | None
    semantic_score_avg_delta: float | None
    avg_latency_ms_delta: float | None


class AgentFeedbackCreatePayload(BaseModel):
    rating: str = Field(min_length=2, max_length=8)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    sources: list[str] = Field(default_factory=list)
    comment: str | None = None
    expected_answer: str | None = None
    session_id: str | None = Field(default=None, min_length=1)
    source_channel: str | None = Field(default=None, min_length=1)


class AgentFeedbackSummaryPayload(BaseModel):
    company_id: str
    agent_id: str
    feedback_total: int
    thumbs_up: int
    thumbs_down: int
    positive_rate: float
    with_comment: int
    with_expected_answer: int


class ChatResponsePayload(BaseModel):
    trace_id: str
    company_id: str
    session_id: str
    answer: str
    route: str
    route_reason: str
    intent_label: str
    intent_confidence: float
    sources: list[str]
    escalation_required: bool
    delivery_status: str | None = None
    delivery_message_id: str | None = None
    delivery_error: str | None = None


def _parse_rag_intents(raw: str) -> set[str]:
    values = [item.strip() for item in raw.split(",")]
    return {value for value in values if value}


def _cors_allowed_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://localhost:3001,http://localhost:4011,"
        "http://localhost:5500,"
        "http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:4011,"
        "http://127.0.0.1:5500",
    )
    return [item.strip() for item in raw.split(",") if item.strip()]


def _public_widget_allowed_origins() -> list[str]:
    raw = os.getenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "*").strip()
    if not raw:
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]


def _public_widget_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    allowed = _public_widget_allowed_origins()
    if "*" in allowed:
        return True
    return origin in allowed


def _public_widget_rate_limit_window_seconds() -> int:
    raw = os.getenv("PUBLIC_WIDGET_RATE_LIMIT_WINDOW_SECONDS", "60").strip()
    try:
        value = int(raw)
    except ValueError:
        return 60
    return max(1, value)


def _public_widget_rate_limit_max_requests() -> int:
    raw = os.getenv("PUBLIC_WIDGET_RATE_LIMIT_MAX_REQUESTS", "30").strip()
    try:
        value = int(raw)
    except ValueError:
        return 30
    return max(1, value)


def _public_widget_signing_secret() -> str:
    secret = os.getenv("PUBLIC_WIDGET_SIGNING_SECRET", "").strip()
    if secret:
        return secret
    return os.getenv("AUTH_SECRET_KEY", "").strip()


def _public_widget_token(agent_id: str, company_id: str) -> str:
    secret = _public_widget_signing_secret()
    if not secret:
        raise RuntimeError(
            "PUBLIC_WIDGET_SIGNING_SECRET no configurado (o AUTH_SECRET_KEY vacio)"
        )
    payload = f"{agent_id}:{company_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _public_widget_api_base_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_WIDGET_API_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def _public_widget_api_base_url_internal(x_public_base_url: str | None) -> str:
    override = (x_public_base_url or "").strip()
    if override:
        return override.rstrip("/")

    configured = os.getenv("PUBLIC_WIDGET_API_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")

    return "http://localhost:8080"


def _public_widget_session_id(widget_id: str, session_id: str | None) -> str:
    clean = (session_id or "").strip()
    if clean:
        return clean
    return f"widget-{widget_id[:8]}-{os.urandom(6).hex()}"


def _public_widget_client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _public_widget_rate_limit_retry_after(widget_id: str, client_id: str) -> int | None:
    window_seconds = _public_widget_rate_limit_window_seconds()
    max_requests = _public_widget_rate_limit_max_requests()
    key = f"{widget_id}:{client_id}"
    now = time.time()

    with _PUBLIC_WIDGET_RATE_LOCK:
        previous = _PUBLIC_WIDGET_RATE_EVENTS.get(key, [])
        recent = [timestamp for timestamp in previous if now - timestamp < window_seconds]

        if len(recent) >= max_requests:
            oldest = recent[0]
            retry_after = max(1, int(window_seconds - (now - oldest)))
            _PUBLIC_WIDGET_RATE_EVENTS[key] = recent
            return retry_after

        recent.append(now)
        _PUBLIC_WIDGET_RATE_EVENTS[key] = recent
        return None


def _public_widget_snippet(api_base_url: str, widget_id: str, widget_token: str) -> str:
    payload = {
        "apiBaseUrl": api_base_url,
        "widgetId": widget_id,
        "widgetToken": widget_token,
    }
    config_json = json.dumps(payload, ensure_ascii=True)
    snippet_template = """<style>
#northline-agent-widget-root{position:fixed;right:22px;bottom:22px;z-index:9999;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}
#northline-agent-widget-toggle{border:0;border-radius:999px;background:#0f766e;color:#fff;padding:12px 16px;cursor:pointer;font-weight:600;box-shadow:0 12px 24px rgba(15,118,110,.28);}
#northline-agent-widget-panel{width:min(380px,calc(100vw - 24px));height:min(540px,70vh);background:#fff;border:1px solid #dbe2ea;border-radius:14px;box-shadow:0 24px 46px rgba(15,23,42,.18);display:flex;flex-direction:column;overflow:hidden;opacity:0;transform:translateY(12px) scale(.98);pointer-events:none;transition:all .2s ease;margin-top:10px;}
#northline-agent-widget-root.open #northline-agent-widget-panel{opacity:1;transform:translateY(0) scale(1);pointer-events:auto;}
#northline-agent-widget-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;background:#0f172a;color:#fff;}
#northline-agent-widget-header strong{font-size:14px;}
#northline-agent-widget-close{border:0;background:transparent;color:#fff;font-size:20px;line-height:1;cursor:pointer;padding:0 4px;}
#northline-agent-widget-messages{flex:1;overflow:auto;padding:12px;display:grid;gap:8px;background:#f8fafc;}
.northline-msg{padding:9px 10px;border:1px solid #dbe2ea;border-radius:10px;font-size:14px;line-height:1.35;white-space:pre-wrap;word-break:break-word;}
.northline-msg.user{background:#e8f7f5;border-color:#b8e3dd;}
.northline-msg.assistant{background:#fff;}
#northline-agent-widget-form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;padding:10px;border-top:1px solid #e2e8f0;background:#fff;}
#northline-agent-widget-input{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #cdd7e3;}
#northline-agent-widget-send{padding:10px 12px;border:0;border-radius:8px;background:#0f766e;color:#fff;cursor:pointer;}
@media (max-width:640px){#northline-agent-widget-root{right:10px;left:10px;bottom:10px;}#northline-agent-widget-panel{width:100%;}}
</style>
<div id="northline-agent-widget-root">
  <button id="northline-agent-widget-toggle" type="button" aria-expanded="false">Abrir chat</button>
  <section id="northline-agent-widget-panel" role="dialog" aria-label="Chat de soporte">
    <header id="northline-agent-widget-header">
      <strong>Soporte virtual</strong>
      <button id="northline-agent-widget-close" type="button" aria-label="Cerrar chat">x</button>
    </header>
    <div id="northline-agent-widget-messages" aria-live="polite"></div>
    <form id="northline-agent-widget-form">
      <input id="northline-agent-widget-input" type="text" placeholder="Escribe tu consulta" />
      <button id="northline-agent-widget-send" type="submit">Enviar</button>
    </form>
  </section>
</div>
<script>
(function(){
  const cfg = __CFG_JSON__;
  const root = document.getElementById("northline-agent-widget-root");
  const toggle = document.getElementById("northline-agent-widget-toggle");
  const panel = document.getElementById("northline-agent-widget-panel");
  const closeBtn = document.getElementById("northline-agent-widget-close");
  const messages = document.getElementById("northline-agent-widget-messages");
  const form = document.getElementById("northline-agent-widget-form");
  const input = document.getElementById("northline-agent-widget-input");
  const sendBtn = document.getElementById("northline-agent-widget-send");
  if (!root || !toggle || !panel || !closeBtn || !messages || !form || !input || !sendBtn) return;

  function setOpen(next){
    if (next) {
      root.classList.add("open");
      toggle.setAttribute("aria-expanded", "true");
      toggle.textContent = "Chat abierto";
      setTimeout(function(){ input.focus(); }, 30);
    } else {
      root.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.textContent = "Abrir chat";
    }
  }

  toggle.addEventListener("click", function(){
    const isOpen = root.classList.contains("open");
    setOpen(!isOpen);
  });
  closeBtn.addEventListener("click", function(){ setOpen(false); });

  function randomId() {
    return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : Math.random().toString(36).slice(2);
  }

  const externalUserId = String(window.NORTHLINE_WIDGET_EXTERNAL_USER_ID || "").trim() || null;
  const identityScope = externalUserId ? ("user_" + externalUserId) : "visitor_anonymous";
  const sessionStorageScope = externalUserId ? window.localStorage : window.sessionStorage;
  const historyStorageScope = externalUserId ? window.localStorage : window.sessionStorage;

  const visitorKey = "northline_agent_widget_visitor_" + cfg.widgetId + "_" + identityScope;
  let visitorId = sessionStorageScope.getItem(visitorKey);
  if (!visitorId) {
    visitorId = randomId();
    sessionStorageScope.setItem(visitorKey, visitorId);
  }

  const sessionKey = "northline_agent_widget_session_" + cfg.widgetId + "_" + identityScope;
  let sessionId = sessionStorageScope.getItem(sessionKey);
  if (!sessionId) {
    sessionId = randomId();
    sessionStorageScope.setItem(sessionKey, sessionId);
  }

  const historyKey = "northline_agent_widget_history_" + cfg.widgetId + "_" + identityScope;

  function loadHistory() {
    const raw = historyStorageScope.getItem(historyKey);
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(function(item){
        return item && (item.role === "user" || item.role === "assistant") && typeof item.text === "string";
      });
    } catch (_err) {
      return [];
    }
  }

  function saveHistory(history) {
    const compact = history.slice(-30);
    historyStorageScope.setItem(historyKey, JSON.stringify(compact));
  }

  let history = loadHistory();

  function addBubble(role, text, persist){
    const row = document.createElement("div");
    row.className = "northline-msg " + (role === "user" ? "user" : "assistant");
    row.textContent = text;
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;

    if (persist !== false) {
      history.push({ role: role, text: text, ts: Date.now() });
      saveHistory(history);
    }
  }

  if (history.length > 0) {
    history.forEach(function(item){
      addBubble(item.role, item.text, false);
    });
  } else {
    addBubble("assistant", "Hola! Soy tu asistente. Contame en que te ayudo.", true);
  }

  form.addEventListener("submit", async function(ev){
    ev.preventDefault();
    const text = (input.value || "").trim();
    if (!text) return;

    addBubble("user", text, true);
    input.value = "";
    sendBtn.disabled = true;
    sendBtn.textContent = "...";

    try {
      const response = await fetch(cfg.apiBaseUrl + "/public/widget/chat", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({
          widget_id: cfg.widgetId,
          widget_token: cfg.widgetToken,
          session_id: sessionId,
          visitor_id: visitorId,
          external_user_id: externalUserId,
          message: text
        })
      });

      let data = null;
      try {
        data = await response.json();
      } catch (_ignored) {
        data = null;
      }

      if (!response.ok) {
        const detail = data && data.detail ? data.detail : "No se pudo obtener respuesta";
        throw new Error(detail);
      }

      addBubble("assistant", (data && data.answer) ? data.answer : "Sin respuesta", true);
    } catch (error) {
      addBubble("assistant", "Error del widget: " + (error && error.message ? error.message : "sin detalle"), true);
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "Enviar";
    }
  });
})();
</script>"""
    return snippet_template.replace("__CFG_JSON__", config_json)


def _build_service() -> ChatService:
    load_dotenv()
    configured_backend = os.getenv("CHAT_SESSION_BACKEND", "auto").strip().lower()
    if configured_backend == "auto":
        configured_backend = "redis" if os.getenv("REDIS_URL", "").strip() else "memory"

    config = ChatServiceConfig(
        rag_index_path=os.getenv("RAG_INDEX_PATH", "models/rag_index.joblib"),
        intent_model_path=os.getenv("INTENT_MODEL_PATH", "models/intent_router.joblib"),
        use_openai=os.getenv("CHAT_USE_OPENAI", "false").lower() == "true",
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        generation_provider=os.getenv("RAG_GENERATION_PROVIDER", "auto"),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        confidence_threshold=float(os.getenv("CHAT_CONFIDENCE_THRESHOLD", "0.45")),
        rag_intents=_parse_rag_intents(os.getenv("CHAT_RAG_INTENTS", "")),
        session_backend=configured_backend,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        redis_key_prefix=os.getenv("REDIS_KEY_PREFIX", "chat_session"),
        redis_ttl_seconds=int(os.getenv("REDIS_TTL_SECONDS", "86400")),
        max_session_turns=int(os.getenv("CHAT_MAX_SESSION_TURNS", "12")),
    )

    backend = config.session_backend.strip().lower()
    if backend == "redis":
        store = RedisSessionStore(
            redis_url=config.redis_url,
            key_prefix=config.redis_key_prefix,
            max_turns=config.max_session_turns,
            ttl_seconds=config.redis_ttl_seconds,
        )
    else:
        store = InMemorySessionStore(max_turns=config.max_session_turns)

    return ChatService(config=config, session_store=store)


def _build_session_store_for_agents(
    *,
    max_turns: int,
):
    backend = os.getenv("AGENT_CHAT_SESSION_BACKEND", "auto").strip().lower()
    if backend == "auto":
        backend = "redis" if os.getenv("REDIS_URL", "").strip() else "memory"

    if backend == "redis":
        redis_url = os.getenv("REDIS_URL", "").strip()
        if not redis_url:
            logger.warning(
                "AGENT_CHAT_SESSION_BACKEND=redis pero REDIS_URL no esta definido; fallback memory"
            )
        else:
            return RedisSessionStore(
                redis_url=redis_url,
                key_prefix=os.getenv("AGENT_CHAT_REDIS_KEY_PREFIX", "agent_chat_session"),
                max_turns=max_turns,
                ttl_seconds=int(os.getenv("AGENT_CHAT_REDIS_TTL_SECONDS", "86400")),
            )

    return InMemorySessionStore(max_turns=max_turns)


def _chat_auth_compat_mode() -> bool:
    return os.getenv("CHAT_AUTH_COMPAT_MODE", "true").strip().lower() == "true"


def _persistence_backend() -> str:
    backend = os.getenv("PERSISTENCE_BACKEND", "").strip().lower()
    if backend in {"sqlite", "memory", "postgres"}:
        return backend
    if os.getenv("POSTGRES_DSN", "").strip() or os.getenv("DATABASE_URL", "").strip():
        return "postgres"
    return "sqlite"


def _postgres_dsn() -> str:
    candidate = (
        os.getenv("POSTGRES_DSN", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )
    if candidate:
        return candidate
    raise ValueError(
        "POSTGRES_DSN o DATABASE_URL es requerido cuando PERSISTENCE_BACKEND=postgres"
    )


def _sqlite_db_path() -> str:
    default_path = (
        Path(__file__).resolve().parent.parent / "data" / "local_api.db"
    )
    return os.getenv("SQLITE_DB_PATH", str(default_path))


def _build_identity_stack() -> tuple[AuthService, TenancyService, TokenService]:
    load_dotenv()
    token_service = TokenService.from_env()
    backend = _persistence_backend()
    if backend == "sqlite":
        db_path = _sqlite_db_path()
        logger.info("sqlite_db_path=%s", db_path)
        store = SQLiteIdentityStore(db_path)
    elif backend == "postgres":
        store = PostgresIdentityStore(_postgres_dsn())
    else:
        store = InMemoryIdentityStore()

    logger.info("identity_store_backend=%s", backend)
    auth_service = AuthService(
        user_repository=store,
        refresh_repository=store,
        membership_repository=store,
        token_service=token_service,
    )
    tenancy_service = TenancyService(
        organization_repository=store,
        membership_repository=store,
    )
    return auth_service, tenancy_service, token_service


def _build_llm_settings_service() -> TenantLlmSettingsService:
    load_dotenv()
    backend = _persistence_backend()
    if backend == "sqlite":
        store = SQLiteTenantLlmSettingsStore(_sqlite_db_path())
    elif backend == "postgres":
        store = PostgresTenantLlmSettingsStore(_postgres_dsn())
    else:
        store = InMemoryTenantLlmSettingsStore()

    return TenantLlmSettingsService(
        store=store,
        default_generation_provider=os.getenv("RAG_GENERATION_PROVIDER", "auto"),
        default_openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        default_anthropic_model=os.getenv(
            "ANTHROPIC_MODEL", "claude-sonnet-4-6"
        ),
    )


def _build_agent_service(llm_settings_service: TenantLlmSettingsService | None) -> AgentService:
    load_dotenv()
    backend = _persistence_backend()
    if backend == "sqlite":
        repository = SQLiteAgentRepository(_sqlite_db_path())
    elif backend == "postgres":
        repository = PostgresAgentRepository(_postgres_dsn())
    else:
        repository = InMemoryAgentRepository()

    logger.info("agent_repository_backend=%s", backend)
    conversation_policy = build_conversation_policy_from_env()
    session_store = _build_session_store_for_agents(
        max_turns=int(os.getenv("AGENT_CHAT_MAX_SESSION_TURNS", "12")),
    )
    return AgentService(
        repository=repository,
        llm_settings_service=llm_settings_service,
        conversation_policy=conversation_policy,
        session_store=session_store,
        knowledge_root=os.getenv("AGENTS_KNOWLEDGE_ROOT", "knowledge_base/agents"),
        index_root=os.getenv("AGENTS_INDEX_ROOT", "models/agents"),
    )


class EvaluationJobStore:
    def create(self, row: dict[str, Any]) -> None:
        raise NotImplementedError

    def get(self, job_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        run: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        raise NotImplementedError


class InMemoryEvaluationJobStore(EvaluationJobStore):
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._rows[str(row.get("job_id"))] = dict(row)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(job_id)
            return dict(row) if row is not None else None

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        run: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(job_id)
            if row is None:
                return None
            if status is not None:
                row["status"] = status
            row["error"] = error
            if run is not None:
                row["run"] = run
            row["updated_at"] = _now_iso()
            self._rows[job_id] = row
            return dict(row)


class SQLiteEvaluationJobStore(EvaluationJobStore):
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_jobs (
                    job_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sample_size INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT,
                    run_json TEXT
                )
                """
            )

    def create(self, row: dict[str, Any]) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO evaluation_jobs
                    (job_id, agent_id, company_id, status, sample_size, created_at, updated_at, error, run_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("job_id"),
                        row.get("agent_id"),
                        row.get("company_id"),
                        row.get("status"),
                        row.get("sample_size"),
                        row.get("created_at"),
                        row.get("updated_at"),
                        row.get("error"),
                        json.dumps(row.get("run"), ensure_ascii=True) if row.get("run") is not None else None,
                    ),
                )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT job_id, agent_id, company_id, status, sample_size, created_at, updated_at, error, run_json
                FROM evaluation_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            run_json = row[8]
            run_payload = json.loads(run_json) if run_json else None
            return {
                "job_id": row[0],
                "agent_id": row[1],
                "company_id": row[2],
                "status": row[3],
                "sample_size": row[4],
                "created_at": row[5],
                "updated_at": row[6],
                "error": row[7],
                "run": run_payload,
            }

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        run: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            current = self.get(job_id)
            if current is None:
                return None
            next_row = dict(current)
            if status is not None:
                next_row["status"] = status
            next_row["error"] = error
            if run is not None:
                next_row["run"] = run
            next_row["updated_at"] = _now_iso()
            self.create(next_row)
            return next_row


class PostgresEvaluationJobStore(EvaluationJobStore):
    def __init__(self, dsn: str, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = schema
        self._lock = threading.Lock()
        try:
            import psycopg  # type: ignore
        except ImportError as exc:
            raise ImportError("psycopg no esta instalado para EVAL_JOB_STORAGE_BACKEND=postgres") from exc
        self._psycopg = psycopg
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(self.dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.schema}.evaluation_jobs (
                        job_id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        company_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        sample_size INTEGER,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        error TEXT,
                        run_json JSONB
                    )
                    """
                )

    def create(self, row: dict[str, Any]) -> None:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self.schema}.evaluation_jobs
                        (job_id, agent_id, company_id, status, sample_size, created_at, updated_at, error, run_json)
                        VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz, %s, %s::jsonb)
                        ON CONFLICT (job_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            sample_size = EXCLUDED.sample_size,
                            updated_at = EXCLUDED.updated_at,
                            error = EXCLUDED.error,
                            run_json = EXCLUDED.run_json
                        """,
                        (
                            row.get("job_id"),
                            row.get("agent_id"),
                            row.get("company_id"),
                            row.get("status"),
                            row.get("sample_size"),
                            row.get("created_at"),
                            row.get("updated_at"),
                            row.get("error"),
                            json.dumps(row.get("run"), ensure_ascii=True) if row.get("run") is not None else None,
                        ),
                    )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT job_id, agent_id, company_id, status, sample_size,
                           created_at::text, updated_at::text, error, run_json
                    FROM {self.schema}.evaluation_jobs
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {
                    "job_id": row[0],
                    "agent_id": row[1],
                    "company_id": row[2],
                    "status": row[3],
                    "sample_size": row[4],
                    "created_at": row[5],
                    "updated_at": row[6],
                    "error": row[7],
                    "run": row[8],
                }

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        run: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            current = self.get(job_id)
            if current is None:
                return None
            next_row = dict(current)
            if status is not None:
                next_row["status"] = status
            next_row["error"] = error
            if run is not None:
                next_row["run"] = run
            next_row["updated_at"] = _now_iso()
            self.create(next_row)
            return next_row


def _build_evaluation_job_store() -> EvaluationJobStore:
    configured = os.getenv("EVAL_JOB_STORAGE_BACKEND", "auto").strip().lower()
    if configured == "auto":
        configured = "sqlite" if _persistence_backend() == "sqlite" else "memory"

    if configured == "postgres":
        dsn = os.getenv("EVAL_JOB_POSTGRES_DSN", "").strip()
        schema = os.getenv("EVAL_JOB_POSTGRES_SCHEMA", "public").strip() or "public"
        if not dsn:
            logger.warning("EVAL_JOB_STORAGE_BACKEND=postgres sin EVAL_JOB_POSTGRES_DSN; fallback sqlite")
            configured = "sqlite"
        else:
            try:
                return PostgresEvaluationJobStore(dsn=dsn, schema=schema)
            except Exception as exc:
                logger.warning("No se pudo iniciar PostgresEvaluationJobStore: %s; fallback sqlite", exc)
                configured = "sqlite"

    if configured == "sqlite":
        try:
            return SQLiteEvaluationJobStore(_sqlite_db_path())
        except Exception as exc:
            logger.warning("No se pudo iniciar SQLiteEvaluationJobStore: %s; fallback memory", exc)
            return InMemoryEvaluationJobStore()

    return InMemoryEvaluationJobStore()


class EvaluationJobQueue:
    def enqueue(self, job_id: str) -> None:
        raise NotImplementedError

    def dequeue(self, timeout_seconds: int = 2) -> str | None:
        raise NotImplementedError


class InMemoryEvaluationJobQueue(EvaluationJobQueue):
    def __init__(self) -> None:
        self._queue: stdlib_queue.Queue[str] = stdlib_queue.Queue()

    def enqueue(self, job_id: str) -> None:
        self._queue.put(job_id)

    def dequeue(self, timeout_seconds: int = 2) -> str | None:
        try:
            return self._queue.get(timeout=timeout_seconds)
        except stdlib_queue.Empty:
            return None


class RedisEvaluationJobQueue(EvaluationJobQueue):
    def __init__(self, redis_url: str, key: str = "eval_job_queue") -> None:
        try:
            import redis
        except ImportError as exc:
            raise ImportError("redis no esta instalado para EVAL_JOB_QUEUE_BACKEND=redis") from exc
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.key = key

    def enqueue(self, job_id: str) -> None:
        self.client.rpush(self.key, job_id)

    def dequeue(self, timeout_seconds: int = 2) -> str | None:
        item = self.client.brpop(self.key, timeout=max(1, timeout_seconds))
        if not item:
            return None
        if isinstance(item, tuple) and len(item) == 2:
            return str(item[1])
        return None


def _build_evaluation_job_queue() -> EvaluationJobQueue:
    configured = os.getenv("EVAL_JOB_QUEUE_BACKEND", "auto").strip().lower()
    if configured == "auto":
        configured = "redis" if os.getenv("REDIS_URL", "").strip() else "memory"

    if configured == "redis":
        redis_url = os.getenv("EVAL_JOB_QUEUE_REDIS_URL", "").strip() or os.getenv("REDIS_URL", "").strip()
        redis_key = os.getenv("EVAL_JOB_QUEUE_KEY", "eval_job_queue").strip() or "eval_job_queue"
        if not redis_url:
            logger.warning("EVAL_JOB_QUEUE_BACKEND=redis sin REDIS_URL; fallback memory")
            return InMemoryEvaluationJobQueue()
        try:
            return RedisEvaluationJobQueue(redis_url=redis_url, key=redis_key)
        except Exception as exc:
            logger.warning("No se pudo iniciar RedisEvaluationJobQueue: %s; fallback memory", exc)
            return InMemoryEvaluationJobQueue()

    return InMemoryEvaluationJobQueue()


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    if not authorization.lower().startswith("bearer "):
        return ""
    return authorization[7:].strip()


def _membership_payload(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"org_id": item.get("org_id", ""), "role": item.get("role", "member")}
        for item in items
    ]


def _to_agent_payload(agent, documents_count: int) -> AgentPayload:
    indexed_at = agent.indexed_at.isoformat() if agent.indexed_at else None
    return AgentPayload(
        agent_id=agent.agent_id,
        org_id=agent.org_id,
        company_id=agent.company_id,
        name=agent.name,
        objective=agent.objective,
        tone=agent.tone,
        description=agent.description,
        rag_backend=agent.rag_backend,
        generation_provider=agent.generation_provider,
        use_openai_generation=agent.use_openai_generation,
        openai_model=agent.openai_model,
        knowledge_dir=agent.knowledge_dir,
        index_path=agent.index_path,
        indexed_at=indexed_at,
        documents_count=documents_count,
    )


def _mask_secret(secret: str) -> str | None:
    token = (secret or "").strip()
    if not token:
        return None
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def _settings_payload(settings: TenantLlmSettings) -> TenantLlmSettingsPayload:
    env_openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    env_anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    has_tenant_openai_key = bool(settings.openai_api_key)
    has_tenant_anthropic_key = bool(settings.anthropic_api_key)
    has_openai_api_key = has_tenant_openai_key or bool(env_openai_key)
    has_anthropic_api_key = has_tenant_anthropic_key or bool(env_anthropic_key)

    openai_source = "tenant" if has_tenant_openai_key else "env" if env_openai_key else "none"
    anthropic_source = (
        "tenant" if has_tenant_anthropic_key else "env" if env_anthropic_key else "none"
    )

    openai_masked = _mask_secret(settings.openai_api_key) or _mask_secret(env_openai_key)
    anthropic_masked = _mask_secret(settings.anthropic_api_key) or _mask_secret(env_anthropic_key)

    return TenantLlmSettingsPayload(
        company_id=settings.company_id,
        generation_provider=settings.generation_provider,
        openai_model=settings.openai_model,
        anthropic_model=settings.anthropic_model,
        has_openai_api_key=has_openai_api_key,
        has_anthropic_api_key=has_anthropic_api_key,
        openai_api_key_masked=openai_masked,
        anthropic_api_key_masked=anthropic_masked,
        openai_key_source=openai_source,
        anthropic_key_source=anthropic_source,
        updated_at=settings.updated_at.isoformat(),
    )


def _document_payload(document) -> AgentDocumentPayload:
    indexed_at = document.indexed_at.isoformat() if document.indexed_at else None
    summary_updated_at = (
        document.summary_updated_at.isoformat() if document.summary_updated_at else None
    )
    return AgentDocumentPayload(
        document_id=document.document_id,
        agent_id=document.agent_id,
        filename=document.filename,
        size_bytes=document.size_bytes,
        status=document.status,
        indexed_at=indexed_at,
        error_message=document.error_message,
        created_at=document.created_at.isoformat(),
        operational_section=document.operational_section,
        learning_summary=document.learning_summary,
        summary_updated_at=summary_updated_at,
    )


def _document_content_payload(document, content: str) -> AgentDocumentContentPayload:
    return AgentDocumentContentPayload(
        document_id=document.document_id,
        agent_id=document.agent_id,
        filename=document.filename,
        status=document.status,
        created_at=document.created_at.isoformat(),
        content=content,
    )


def _whatsapp_webhook_url(request: Request) -> str:
    return ""


def _whatsapp_webhook_url_internal(x_public_base_url: str | None) -> str:
    return ""


def _whatsapp_config_payload(
    *,
    agent_id: str,
    company_id: str,
    webhook_url: str,
    config: dict[str, str | None],
) -> AgentWhatsAppConfigPayload:
    return AgentWhatsAppConfigPayload(
        agent_id=agent_id,
        company_id=company_id,
        webhook_url=webhook_url,
        phone_number_id=config.get("phone_number_id"),
        business_account_id=config.get("business_account_id"),
        verify_token=config.get("verify_token"),
        updated_at=config.get("updated_at"),
    )


app = FastAPI(title="Clasificacion + Hybrid RAG API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    chat_service = _build_service()
    startup_error = ""
except Exception as exc:
    chat_service = None
    startup_error = str(exc)

try:
    auth_service, tenancy_service, token_service = _build_identity_stack()
except Exception as exc:
    auth_service = None
    tenancy_service = None
    token_service = None
    startup_error = f"{startup_error}; auth: {exc}".strip("; ")

try:
    llm_settings_service = _build_llm_settings_service()
except Exception as exc:
    llm_settings_service = None
    startup_error = f"{startup_error}; settings: {exc}".strip("; ")

try:
    agent_service = _build_agent_service(llm_settings_service)
except Exception as exc:
    agent_service = None
    startup_error = f"{startup_error}; agents: {exc}".strip("; ")

try:
    chat_audit_service = build_chat_audit_service_from_env()
except Exception as exc:
    chat_audit_service = None
    startup_error = f"{startup_error}; audit: {exc}".strip("; ")

try:
    retrieval_audit_service = build_retrieval_audit_service_from_env()
except Exception as exc:
    retrieval_audit_service = None
    startup_error = f"{startup_error}; retrieval-audit: {exc}".strip("; ")

try:
    agent_feedback_service = build_agent_feedback_service_from_env()
except Exception as exc:
    agent_feedback_service = None
    startup_error = f"{startup_error}; feedback: {exc}".strip("; ")

try:
    evaluation_job_store = _build_evaluation_job_store()
except Exception as exc:
    evaluation_job_store = InMemoryEvaluationJobStore()
    startup_error = f"{startup_error}; eval-jobs memory fallback: {exc}".strip("; ")

try:
    evaluation_job_queue = _build_evaluation_job_queue()
except Exception as exc:
    evaluation_job_queue = InMemoryEvaluationJobQueue()
    startup_error = f"{startup_error}; eval-queue memory fallback: {exc}".strip("; ")

evaluation_worker_started = False


def _require_principal(authorization: str | None) -> AuthPrincipal:
    if token_service is None:
        raise HTTPException(status_code=503, detail="Auth no disponible en este entorno")

    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Falta Bearer token")

    try:
        return token_service.validate_access_token(token)
    except AuthTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _require_internal_context(
    x_company_id: str | None,
    x_org_id: str | None,
    x_user_id: str | None,
    x_request_id: str | None,
    x_platform_signature: str | None,
    x_platform_timestamp: str | None,
) -> tuple[str, str, str, str]:
    company_id = (x_company_id or "").strip()
    org_id = (x_org_id or "").strip()
    user_id = (x_user_id or "").strip()
    request_id = (x_request_id or "").strip()

    if not company_id:
        raise HTTPException(status_code=400, detail="Falta header X-Company-Id")
    if not org_id:
        raise HTTPException(status_code=400, detail="Falta header X-Org-Id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Falta header X-User-Id")
    if not request_id:
        request_id = str(uuid4())

    _validate_internal_signature(
        company_id=company_id,
        org_id=org_id,
        user_id=user_id,
        request_id=request_id,
        signature=x_platform_signature,
        timestamp=x_platform_timestamp,
    )

    return company_id, org_id, user_id, request_id


def _validate_internal_signature(
    company_id: str,
    org_id: str,
    user_id: str,
    request_id: str,
    signature: str | None,
    timestamp: str | None,
) -> None:
    shared_secret = os.getenv("AI_ENGINE_SHARED_SECRET", "").strip()
    if not shared_secret:
        return

    clean_signature = (signature or "").strip()
    clean_timestamp = (timestamp or "").strip()
    if not clean_signature:
        raise HTTPException(status_code=401, detail="Falta header X-Platform-Signature")
    if not clean_timestamp:
        raise HTTPException(status_code=401, detail="Falta header X-Platform-Timestamp")

    try:
        sent_epoch = int(clean_timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Timestamp de firma invalido") from exc

    now_epoch = int(time.time())
    if abs(now_epoch - sent_epoch) > 300:
        raise HTTPException(status_code=401, detail="Firma expirada")

    canonical = "\n".join([
        clean_timestamp,
        company_id,
        org_id,
        user_id,
        request_id,
    ])
    expected = hmac.new(
        shared_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, clean_signature):
        raise HTTPException(status_code=401, detail="Firma interna invalida")


def _to_audit_summary_payload(row: ChatAuditSummaryRow) -> ChatAuditSummaryRowPayload:
    return ChatAuditSummaryRowPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        assistant_messages=row.assistant_messages,
        cached_responses=row.cached_responses,
        generic_repeat_responses=row.generic_repeat_responses,
        closed_conversations=row.closed_conversations,
    )


def _to_audit_cost_payload(row: ChatAuditCostRow) -> ChatAuditCostRowPayload:
    return ChatAuditCostRowPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        assistant_messages=row.assistant_messages,
        llm_messages=row.llm_messages,
        avoided_llm_calls=row.avoided_llm_calls,
        estimated_spent_usd=row.estimated_spent_usd,
        estimated_saved_usd=row.estimated_saved_usd,
    )


def _to_retrieval_summary_payload(
    row: RetrievalAuditSummaryRow,
) -> RetrievalAuditSummaryRowPayload:
    return RetrievalAuditSummaryRowPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        queries_total=row.queries_total,
        answers_with_sources=row.answers_with_sources,
        answers_without_sources=row.answers_without_sources,
        fallback_count=row.fallback_count,
        avg_retrieved_chunks=row.avg_retrieved_chunks,
        avg_retrieval_score=row.avg_retrieval_score,
        avg_latency_ms=row.avg_latency_ms,
    )


def _to_retrieval_backend_metrics_payload(
    row: RetrievalBackendMetrics,
) -> RetrievalBackendMetricsPayload:
    return RetrievalBackendMetricsPayload(
        backend=row.backend,
        queries_total=row.queries_total,
        answers_with_sources=row.answers_with_sources,
        fallback_count=row.fallback_count,
        avg_retrieval_score=row.avg_retrieval_score,
        avg_latency_ms=row.avg_latency_ms,
    )


def _to_retrieval_comparison_payload(
    row: RetrievalComparisonRow,
) -> RetrievalComparisonPayload:
    return RetrievalComparisonPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        current_backend=row.current_backend,
        baseline_backend=row.baseline_backend,
        current=_to_retrieval_backend_metrics_payload(row.current),
        baseline=_to_retrieval_backend_metrics_payload(row.baseline) if row.baseline else None,
        grounded_rate_delta=row.grounded_rate_delta,
        fallback_rate_delta=row.fallback_rate_delta,
        score_delta=row.score_delta,
        latency_delta_ms=row.latency_delta_ms,
    )


def _to_rag_decision_record_payload(row: dict[str, object]) -> RagDecisionRecordPayload:
    return RagDecisionRecordPayload(
        recorded_at=str(row.get("recorded_at") or ""),
        agent_id=str(row.get("agent_id") or ""),
        company_id=str(row.get("company_id") or ""),
        decision=str(row.get("decision") or ""),
        current_backend=str(row.get("current_backend") or ""),
        baseline_backend=str(row.get("baseline_backend") or "").strip() or None,
        reason=str(row.get("reason") or ""),
        grounded_rate_delta=float(row["grounded_rate_delta"])
        if row.get("grounded_rate_delta") is not None
        else None,
        fallback_rate_delta=float(row["fallback_rate_delta"])
        if row.get("fallback_rate_delta") is not None
        else None,
        score_delta=float(row["score_delta"]) if row.get("score_delta") is not None else None,
        latency_delta_ms=float(row["latency_delta_ms"])
        if row.get("latency_delta_ms") is not None
        else None,
    )


def _to_evaluation_run_payload(row: dict[str, object]) -> EvaluationRunPayload:
    return EvaluationRunPayload(
        run_id=str(row.get("run_id") or ""),
        recorded_at=str(row.get("recorded_at") or ""),
        agent_id=str(row.get("agent_id") or ""),
        company_id=str(row.get("company_id") or ""),
        rag_backend=str(row.get("rag_backend") or ""),
        cases_total=int(row.get("cases_total") or 0),
        accuracy=float(row.get("accuracy") or 0.0),
        semantic_accuracy=float(row["semantic_accuracy"]) if row.get("semantic_accuracy") is not None else None,
        grounded_rate=float(row.get("grounded_rate") or 0.0),
        fallback_rate=float(row.get("fallback_rate") or 0.0),
        avg_case_score=float(row.get("avg_case_score") or 0.0),
        semantic_score_avg=float(row["semantic_score_avg"]) if row.get("semantic_score_avg") is not None else None,
        avg_latency_ms=float(row.get("avg_latency_ms") or 0.0),
        llm_judge_enabled=bool(row.get("llm_judge_enabled")),
        llm_judge_scored_cases=int(row.get("llm_judge_scored_cases") or 0),
    )


def _to_evaluation_compare_payload(row: dict[str, object]) -> EvaluationComparePayload:
    current = row.get("current")
    baseline = row.get("baseline")
    return EvaluationComparePayload(
        agent_id=str(row.get("agent_id") or ""),
        company_id=str(row.get("company_id") or ""),
        current=_to_evaluation_run_payload(current) if isinstance(current, dict) else None,
        baseline=_to_evaluation_run_payload(baseline) if isinstance(baseline, dict) else None,
        accuracy_delta=float(row["accuracy_delta"]) if row.get("accuracy_delta") is not None else None,
        semantic_accuracy_delta=float(row["semantic_accuracy_delta"]) if row.get("semantic_accuracy_delta") is not None else None,
        grounded_rate_delta=float(row["grounded_rate_delta"]) if row.get("grounded_rate_delta") is not None else None,
        fallback_rate_delta=float(row["fallback_rate_delta"]) if row.get("fallback_rate_delta") is not None else None,
        avg_case_score_delta=float(row["avg_case_score_delta"]) if row.get("avg_case_score_delta") is not None else None,
        semantic_score_avg_delta=float(row["semantic_score_avg_delta"]) if row.get("semantic_score_avg_delta") is not None else None,
        avg_latency_ms_delta=float(row["avg_latency_ms_delta"]) if row.get("avg_latency_ms_delta") is not None else None,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _to_evaluation_job_payload(row: dict[str, Any]) -> EvaluationRunJobPayload:
    run_payload = row.get("run") if isinstance(row.get("run"), dict) else None
    return EvaluationRunJobPayload(
        job_id=str(row.get("job_id") or ""),
        agent_id=str(row.get("agent_id") or ""),
        company_id=str(row.get("company_id") or ""),
        status=str(row.get("status") or "queued"),
        sample_size=int(row["sample_size"]) if row.get("sample_size") is not None else None,
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        error=str(row.get("error") or "").strip() or None,
        run=_to_evaluation_run_payload(run_payload) if run_payload else None,
    )


def _run_evaluation_job_worker(
    *,
    job_id: str,
) -> None:
    if agent_service is None:
        row = evaluation_job_store.get(job_id)
        if row is None:
            return
        evaluation_job_store.update(
            job_id,
            status="failed",
            error="Agent service no disponible",
        )
        return

    row = evaluation_job_store.get(job_id)
    if row is None:
        return

    agent_id = str(row.get("agent_id") or "").strip()
    if not agent_id:
        evaluation_job_store.update(job_id, status="failed", error="agent_id faltante en job")
        return

    agent = agent_service.repository.get_agent(agent_id)
    if agent is None:
        evaluation_job_store.update(job_id, status="failed", error="Agente del job no encontrado")
        return

    sample_size = int(row["sample_size"]) if row.get("sample_size") is not None else None
    evaluation_job_store.update(job_id, status="running", error=None)

    try:
        run = agent_service.run_evaluation(agent=agent, sample_size=sample_size)
        evaluation_job_store.update(job_id, status="succeeded", error=None, run=run)
    except Exception as exc:
        evaluation_job_store.update(job_id, status="failed", error=str(exc))


def _evaluation_worker_loop() -> None:
    logger.info("evaluation_worker_started")
    while True:
        try:
            job_id = evaluation_job_queue.dequeue(timeout_seconds=2)
            if not job_id:
                continue
            _run_evaluation_job_worker(job_id=job_id)
        except Exception as exc:
            logger.warning("evaluation_worker_loop_error detail=%s", exc)


def _start_evaluation_worker_once() -> None:
    global evaluation_worker_started
    if evaluation_worker_started:
        return
    worker = threading.Thread(target=_evaluation_worker_loop, daemon=True, name="evaluation-worker")
    worker.start()
    evaluation_worker_started = True


def _embedded_worker_enabled() -> bool:
    return os.getenv("EVAL_EMBEDDED_WORKER_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run_evaluation_worker_forever() -> None:
    _evaluation_worker_loop()


if _embedded_worker_enabled():
    _start_evaluation_worker_once()


def _evaluation_runs_to_csv(rows: list[dict[str, object]]) -> str:
    header = [
        "run_id",
        "recorded_at",
        "agent_id",
        "company_id",
        "rag_backend",
        "cases_total",
        "accuracy",
        "semantic_accuracy",
        "grounded_rate",
        "fallback_rate",
        "avg_case_score",
        "semantic_score_avg",
        "avg_latency_ms",
        "llm_judge_enabled",
        "llm_judge_scored_cases",
    ]

    def _escape(value: object) -> str:
        text = str(value if value is not None else "")
        text = text.replace('"', '""')
        return f'"{text}"'

    lines = [",".join(header)]
    for row in rows:
        values = [
            row.get("run_id"),
            row.get("recorded_at"),
            row.get("agent_id"),
            row.get("company_id"),
            row.get("rag_backend"),
            row.get("cases_total"),
            row.get("accuracy"),
            row.get("semantic_accuracy"),
            row.get("grounded_rate"),
            row.get("fallback_rate"),
            row.get("avg_case_score"),
            row.get("semantic_score_avg"),
            row.get("avg_latency_ms"),
            row.get("llm_judge_enabled"),
            row.get("llm_judge_scored_cases"),
        ]
        lines.append(",".join(_escape(value) for value in values))

    return "\n".join(lines)


def _to_agent_feedback_summary_payload(
    row: AgentFeedbackSummary,
) -> AgentFeedbackSummaryPayload:
    return AgentFeedbackSummaryPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        feedback_total=row.feedback_total,
        thumbs_up=row.thumbs_up,
        thumbs_down=row.thumbs_down,
        positive_rate=row.positive_rate,
        with_comment=row.with_comment,
        with_expected_answer=row.with_expected_answer,
    )


def _record_chat_audit(record: ChatAuditRecord) -> None:
    if chat_audit_service is None:
        return
    try:
        chat_audit_service.record(record)
    except Exception as exc:
        logger.warning("chat_audit_record_failed detail=%s", exc)


def _record_retrieval_audit(record: RetrievalAuditRecord) -> None:
    if retrieval_audit_service is None:
        return
    try:
        retrieval_audit_service.record(record)
    except Exception as exc:
        logger.warning("retrieval_audit_record_failed detail=%s", exc)


def _resolve_report_companies(
    principal: AuthPrincipal,
    company_id: str | None,
) -> list[str]:
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    if company_id:
        try:
            resolved = tenancy_service.resolve_company_id(
                principal=principal,
                requested_company_id=company_id,
            )
        except TenantContextError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except TenantForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return [resolved]

    discovered: set[str] = set()
    for org_id in allowed_org_ids:
        org = tenancy_service.organization_repository.get_organization(org_id)
        if org is None:
            continue
        discovered.add(org.company_id)
    return sorted(discovered)


@app.get("/health")
def health() -> dict[str, str]:
    if chat_service is None:
        return {"status": "degraded", "error": startup_error}
    if startup_error:
        return {"status": "ok", "warning": startup_error}
    return {"status": "ok"}


@app.get("/reports/chat/summary", response_model=list[ChatAuditSummaryRowPayload])
def chat_report_summary(
    authorization: str | None = Header(default=None),
    company_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> list[ChatAuditSummaryRowPayload]:
    if chat_audit_service is None:
        return []

    principal = _require_principal(authorization)
    target_companies = _resolve_report_companies(principal=principal, company_id=company_id)

    rows: list[ChatAuditSummaryRow] = []
    for target_company in target_companies:
        rows.extend(chat_audit_service.summary(company_id=target_company, since_days=days))

    return [_to_audit_summary_payload(row) for row in rows]


@app.get("/reports/chat/cost-estimate", response_model=list[ChatAuditCostRowPayload])
def chat_report_cost_estimate(
    authorization: str | None = Header(default=None),
    company_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    avg_llm_cost_usd: float = Query(default=0.01, ge=0.0, le=10.0),
) -> list[ChatAuditCostRowPayload]:
    if chat_audit_service is None:
        return []

    principal = _require_principal(authorization)
    target_companies = _resolve_report_companies(principal=principal, company_id=company_id)

    rows: list[ChatAuditCostRow] = []
    for target_company in target_companies:
        rows.extend(
            chat_audit_service.cost_summary(
                avg_llm_cost_usd=avg_llm_cost_usd,
                company_id=target_company,
                since_days=days,
            )
        )

    return [_to_audit_cost_payload(row) for row in rows]


@app.get("/reports/retrieval/summary", response_model=list[RetrievalAuditSummaryRowPayload])
def retrieval_report_summary(
    authorization: str | None = Header(default=None),
    company_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> list[RetrievalAuditSummaryRowPayload]:
    if retrieval_audit_service is None:
        return []

    principal = _require_principal(authorization)
    target_companies = _resolve_report_companies(principal=principal, company_id=company_id)

    rows: list[RetrievalAuditSummaryRow] = []
    for target_company in target_companies:
        rows.extend(retrieval_audit_service.summary(company_id=target_company, since_days=days))

    return [_to_retrieval_summary_payload(row) for row in rows]


@app.get("/agents/{agent_id}/retrieval/compare", response_model=RetrievalComparisonPayload)
def compare_agent_retrieval(
    agent_id: str,
    authorization: str | None = Header(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> RetrievalComparisonPayload:
    if retrieval_audit_service is None:
        current = RetrievalBackendMetricsPayload(
            backend="unknown",
            queries_total=0,
            answers_with_sources=0,
            fallback_count=0,
            avg_retrieval_score=0.0,
            avg_latency_ms=0.0,
        )
        return RetrievalComparisonPayload(
            company_id="",
            agent_id=agent_id,
            current_backend="unknown",
            baseline_backend=None,
            current=current,
            baseline=None,
            grounded_rate_delta=None,
            fallback_rate_delta=None,
            score_delta=None,
            latency_delta_ms=None,
        )
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    comparison = retrieval_audit_service.compare_agent_backends(
        company_id=agent.company_id,
        agent_id=agent.agent_id,
        current_backend=agent.rag_backend,
        since_days=days,
    )
    return _to_retrieval_comparison_payload(comparison)


@app.post("/agents/{agent_id}/retrieval/decision", response_model=RagDecisionRecordPayload)
def create_agent_rag_decision(
    agent_id: str,
    payload: RagDecisionCreatePayload,
    authorization: str | None = Header(default=None),
) -> RagDecisionRecordPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        row = agent_service.save_rag_decision(
            agent=agent,
            decision=payload.decision,
            current_backend=payload.current_backend,
            baseline_backend=payload.baseline_backend,
            reason=payload.reason,
            grounded_rate_delta=payload.grounded_rate_delta,
            fallback_rate_delta=payload.fallback_rate_delta,
            score_delta=payload.score_delta,
            latency_delta_ms=payload.latency_delta_ms,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_rag_decision_record_payload(row)


@app.get("/agents/{agent_id}/retrieval/decision-history", response_model=list[RagDecisionRecordPayload])
def get_agent_rag_decision_history(
    agent_id: str,
    authorization: str | None = Header(default=None),
) -> list[RagDecisionRecordPayload]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        rows = agent_service.list_rag_decision_history(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return [_to_rag_decision_record_payload(row) for row in rows]


@app.get("/agents/{agent_id}/evaluation/dataset", response_model=EvaluationDatasetPayload)
def get_agent_evaluation_dataset(
    agent_id: str,
    authorization: str | None = Header(default=None),
) -> EvaluationDatasetPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        rows = agent_service.get_evaluation_dataset(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return EvaluationDatasetPayload(cases=[EvaluationCasePayload(**row) for row in rows])


@app.post("/agents/{agent_id}/evaluation/dataset", response_model=EvaluationDatasetPayload)
def save_agent_evaluation_dataset(
    agent_id: str,
    payload: EvaluationDatasetPayload,
    authorization: str | None = Header(default=None),
) -> EvaluationDatasetPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        rows = agent_service.save_evaluation_dataset(
            agent,
            cases=[{"question": case.question, "expected_answer": case.expected_answer} for case in payload.cases],
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return EvaluationDatasetPayload(cases=[EvaluationCasePayload(**row) for row in rows])


@app.post("/agents/{agent_id}/evaluation/run", response_model=EvaluationRunPayload)
def run_agent_evaluation(
    agent_id: str,
    payload: EvaluationRunRequestPayload,
    authorization: str | None = Header(default=None),
) -> EvaluationRunPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        run = agent_service.run_evaluation(agent=agent, sample_size=payload.sample_size)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_evaluation_run_payload(run)


@app.post("/agents/{agent_id}/evaluation/run-async", response_model=EvaluationRunJobPayload)
def run_agent_evaluation_async(
    agent_id: str,
    payload: EvaluationRunRequestPayload,
    authorization: str | None = Header(default=None),
) -> EvaluationRunJobPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    now_iso = _now_iso()
    job_id = f"eval-job-{uuid4().hex}"
    row: dict[str, Any] = {
        "job_id": job_id,
        "agent_id": agent.agent_id,
        "company_id": agent.company_id,
        "status": "queued",
        "sample_size": payload.sample_size,
        "created_at": now_iso,
        "updated_at": now_iso,
        "error": None,
        "run": None,
    }
    evaluation_job_store.create(row)

    evaluation_job_queue.enqueue(job_id)
    current_row = evaluation_job_store.get(job_id) or row
    return _to_evaluation_job_payload(current_row)


@app.get("/agents/{agent_id}/evaluation/jobs/{job_id}", response_model=EvaluationRunJobPayload)
def get_agent_evaluation_job(
    agent_id: str,
    job_id: str,
    authorization: str | None = Header(default=None),
) -> EvaluationRunJobPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    row = evaluation_job_store.get(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job de evaluacion no encontrado")
    if row.get("agent_id") != agent.agent_id:
        raise HTTPException(status_code=403, detail="No tenes acceso a este job")
    return _to_evaluation_job_payload(row)


@app.get("/agents/{agent_id}/evaluation/runs", response_model=list[EvaluationRunPayload])
def list_agent_evaluation_runs(
    agent_id: str,
    authorization: str | None = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[EvaluationRunPayload]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        rows = agent_service.list_evaluation_runs(agent=agent, limit=limit)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return [_to_evaluation_run_payload(row) for row in rows]


@app.get("/agents/{agent_id}/evaluation/runs.csv", response_class=PlainTextResponse)
def export_agent_evaluation_runs_csv(
    agent_id: str,
    authorization: str | None = Header(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> PlainTextResponse:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        rows = agent_service.list_evaluation_runs(agent=agent, limit=limit)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    csv_content = _evaluation_runs_to_csv(rows)
    headers = {
        "Content-Disposition": f'attachment; filename="agent-{agent.agent_id}-evaluation-runs.csv"'
    }
    return PlainTextResponse(content=csv_content, headers=headers, media_type="text/csv")


@app.get("/agents/{agent_id}/evaluation/compare-latest", response_model=EvaluationComparePayload)
def compare_latest_agent_evaluation(
    agent_id: str,
    authorization: str | None = Header(default=None),
) -> EvaluationComparePayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        result = agent_service.compare_latest_evaluation_runs(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_evaluation_compare_payload(result)


logger.info("Identity endpoints moved to platform-api: /auth, /me, /orgs")


@app.get("/settings/llm", response_model=TenantLlmSettingsPayload)
def get_llm_settings(
    authorization: str | None = Header(default=None),
    company_id: str | None = Query(default=None),
) -> TenantLlmSettingsPayload:
    if llm_settings_service is None:
        raise HTTPException(status_code=503, detail="Settings no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    try:
        effective_company_id = tenancy_service.resolve_company_id(
            principal=principal,
            requested_company_id=company_id,
        )
    except TenantContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TenantForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    settings = llm_settings_service.get(effective_company_id)
    return _settings_payload(settings)


@app.put("/settings/llm", response_model=TenantLlmSettingsPayload)
def update_llm_settings(
    payload: TenantLlmSettingsUpdatePayload,
    authorization: str | None = Header(default=None),
) -> TenantLlmSettingsPayload:
    if llm_settings_service is None:
        raise HTTPException(status_code=503, detail="Settings no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    try:
        effective_company_id = tenancy_service.resolve_company_id(
            principal=principal,
            requested_company_id=payload.company_id,
        )
    except TenantContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TenantForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    settings = llm_settings_service.update(
        company_id=effective_company_id,
        generation_provider=payload.generation_provider,
        openai_model=payload.openai_model,
        anthropic_model=payload.anthropic_model,
        openai_api_key=payload.openai_api_key,
        anthropic_api_key=payload.anthropic_api_key,
        clear_openai_api_key=payload.clear_openai_api_key,
        clear_anthropic_api_key=payload.clear_anthropic_api_key,
    )
    return _settings_payload(settings)


@app.get("/internal/ai/settings/llm", response_model=TenantLlmSettingsPayload)
def internal_get_llm_settings(
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> TenantLlmSettingsPayload:
    if llm_settings_service is None:
        raise HTTPException(status_code=503, detail="Settings no disponible")

    company_id, _, _, _ = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )
    settings = llm_settings_service.get(company_id)
    return _settings_payload(settings)


@app.put("/internal/ai/settings/llm", response_model=TenantLlmSettingsPayload)
def internal_update_llm_settings(
    payload: TenantLlmSettingsUpdatePayload,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> TenantLlmSettingsPayload:
    if llm_settings_service is None:
        raise HTTPException(status_code=503, detail="Settings no disponible")

    company_id, _, _, _ = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    settings = llm_settings_service.update(
        company_id=company_id,
        generation_provider=payload.generation_provider,
        openai_model=payload.openai_model,
        anthropic_model=payload.anthropic_model,
        openai_api_key=payload.openai_api_key,
        anthropic_api_key=payload.anthropic_api_key,
        clear_openai_api_key=payload.clear_openai_api_key,
        clear_anthropic_api_key=payload.clear_anthropic_api_key,
    )
    return _settings_payload(settings)


@app.post("/internal/ai/agents", response_model=AgentPayload)
def internal_create_agent(
    payload: AgentCreatePayload,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> AgentPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_create_agent request_id=%s user_id=%s org_id=%s company_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
    )

    try:
        agent = agent_service.create_agent(
            org_id=org_id,
            company_id=company_id,
            name=payload.name,
            objective=payload.objective,
            tone=payload.tone,
            description=payload.description,
            rag_backend=payload.rag_backend,
            generation_provider=payload.generation_provider,
            use_openai_generation=payload.use_openai_generation,
            openai_model=payload.openai_model or "gpt-4o-mini",
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    documents = agent_service.list_documents(agent.agent_id)
    return _to_agent_payload(agent, documents_count=len(documents))


@app.get("/internal/ai/agents", response_model=list[AgentPayload])
def internal_list_agents(
    company_id: str | None = Query(default=None),
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> list[AgentPayload]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    header_company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    effective_company_id = (company_id or "").strip() or header_company_id
    if effective_company_id != header_company_id:
        raise HTTPException(status_code=403, detail="company_id de query no coincide con contexto")

    logger.info(
        "internal_list_agents request_id=%s user_id=%s org_id=%s company_id=%s",
        request_id,
        user_id,
        org_id,
        header_company_id,
    )

    agents = agent_service.list_agents(
        allowed_org_ids={org_id},
        company_id=effective_company_id,
    )
    response: list[AgentPayload] = []
    for agent in agents:
        docs_count = len(agent_service.list_documents(agent.agent_id))
        response.append(_to_agent_payload(agent, documents_count=docs_count))
    return response


@app.patch("/internal/ai/agents/{agent_id}", response_model=AgentPayload)
def internal_update_agent(
    agent_id: str,
    payload: AgentUpdatePayload,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> AgentPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_update_agent request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
        updated = agent_service.update_agent(
            agent=agent,
            name=payload.name,
            objective=payload.objective,
            tone=payload.tone,
            description=payload.description,
            rag_backend=payload.rag_backend,
            generation_provider=payload.generation_provider,
            use_openai_generation=payload.use_openai_generation,
            openai_model=payload.openai_model,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    documents = agent_service.list_documents(updated.agent_id)
    return _to_agent_payload(updated, documents_count=len(documents))


@app.delete("/internal/ai/agents/{agent_id}")
def internal_delete_agent(
    agent_id: str,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> dict[str, str]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_delete_agent request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
        removed = agent_service.delete_agent(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "deleted",
        "agent_id": removed.agent_id,
    }


@app.get("/internal/ai/agents/{agent_id}/documents", response_model=list[AgentDocumentPayload])
def internal_list_agent_documents(
    agent_id: str,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> list[AgentDocumentPayload]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_list_documents request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    documents = agent_service.list_documents(agent.agent_id)
    return [_document_payload(document) for document in documents]


@app.post("/internal/ai/agents/{agent_id}/index/rebuild", response_model=AgentIndexPayload)
def internal_rebuild_agent_index(
    agent_id: str,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> AgentIndexPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_rebuild_index request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
        index_result = agent_service.rebuild_index(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return AgentIndexPayload(
        agent_id=agent.agent_id,
        backend=index_result.backend,
        total_documents=index_result.total_documents,
        total_chunks=index_result.total_chunks,
        companies=index_result.companies,
        index_path=str(index_result.index_path),
    )


@app.get("/internal/ai/agents/{agent_id}/index/status", response_model=AgentIndexStatusPayload)
def internal_get_agent_index_status(
    agent_id: str,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> AgentIndexStatusPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_index_status request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    documents = agent_service.list_documents(agent.agent_id)
    indexed = [document for document in documents if document.status == "indexed"]
    failed = [document for document in documents if document.status == "failed"]
    uploaded = [document for document in documents if document.status == "uploaded"]
    last_error = failed[0].error_message if failed else None

    return AgentIndexStatusPayload(
        agent_id=agent.agent_id,
        has_index=Path(agent.index_path).exists(),
        indexed_at=agent.indexed_at.isoformat() if agent.indexed_at else None,
        documents_total=len(documents),
        documents_indexed=len(indexed),
        documents_failed=len(failed),
        documents_uploaded=len(uploaded),
        last_error=last_error,
    )


@app.post("/internal/ai/agents/{agent_id}/documents", response_model=AgentDocumentPayload)
def internal_upload_agent_document(
    agent_id: str,
    payload: InternalAgentDocumentUploadPayload,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> AgentDocumentPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_upload_document request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="content_base64 invalido") from exc

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
        document = agent_service.save_document(
            agent=agent,
            filename=payload.filename,
            content=content,
            operational_section=payload.operational_section,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _document_payload(document)


@app.delete("/internal/ai/agents/{agent_id}/documents/{document_id}")
def internal_delete_agent_document(
    agent_id: str,
    document_id: str,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> dict[str, str]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_delete_document request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s document_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
        document_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
        agent_service.delete_document(agent=agent, document_id=document_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "status": "deleted",
        "document_id": document_id,
    }


@app.post("/agents", response_model=AgentPayload)
def create_agent(
    payload: AgentCreatePayload,
    authorization: str | None = Header(default=None),
) -> AgentPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)

    try:
        effective_company_id = tenancy_service.resolve_company_id(
            principal=principal,
            requested_company_id=payload.company_id,
        )
    except TenantContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TenantForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    organization = tenancy_service.organization_repository.get_organization_by_company_id(
        effective_company_id
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="No existe la organizacion para ese company_id")

    try:
        agent = agent_service.create_agent(
            org_id=organization.org_id,
            company_id=effective_company_id,
            name=payload.name,
            objective=payload.objective,
            tone=payload.tone,
            description=payload.description,
            rag_backend=payload.rag_backend,
            generation_provider=payload.generation_provider,
            use_openai_generation=payload.use_openai_generation,
            openai_model=payload.openai_model or "gpt-4o-mini",
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    documents = agent_service.list_documents(agent.agent_id)
    return _to_agent_payload(agent, documents_count=len(documents))


@app.get("/agents", response_model=list[AgentPayload])
def list_agents(
    authorization: str | None = Header(default=None),
    company_id: str | None = Query(default=None),
) -> list[AgentPayload]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    effective_company_id = None
    if company_id:
        try:
            effective_company_id = tenancy_service.resolve_company_id(
                principal=principal,
                requested_company_id=company_id,
            )
        except TenantContextError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except TenantForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    agents = agent_service.list_agents(
        allowed_org_ids=allowed_org_ids,
        company_id=effective_company_id,
    )
    response: list[AgentPayload] = []
    for agent in agents:
        docs_count = len(agent_service.list_documents(agent.agent_id))
        response.append(_to_agent_payload(agent, documents_count=docs_count))
    return response


@app.patch("/agents/{agent_id}", response_model=AgentPayload)
def update_agent(
    agent_id: str,
    payload: AgentUpdatePayload,
    authorization: str | None = Header(default=None),
) -> AgentPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        updated = agent_service.update_agent(
            agent=agent,
            name=payload.name,
            objective=payload.objective,
            tone=payload.tone,
            description=payload.description,
            rag_backend=payload.rag_backend,
            generation_provider=payload.generation_provider,
            use_openai_generation=payload.use_openai_generation,
            openai_model=payload.openai_model,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    documents = agent_service.list_documents(updated.agent_id)
    return _to_agent_payload(updated, documents_count=len(documents))


@app.delete("/agents/{agent_id}")
def delete_agent(
    agent_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        removed = agent_service.delete_agent(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "deleted",
        "agent_id": removed.agent_id,
    }


@app.get("/agents/{agent_id}/documents", response_model=list[AgentDocumentPayload])
def list_agent_documents(
    agent_id: str,
    authorization: str | None = Header(default=None),
) -> list[AgentDocumentPayload]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    documents = agent_service.list_documents(agent.agent_id)
    return [_document_payload(document) for document in documents]


@app.get(
    "/agents/{agent_id}/documents/{document_id}/content",
    response_model=AgentDocumentContentPayload,
)
def get_agent_document_content(
    agent_id: str,
    document_id: str,
    authorization: str | None = Header(default=None),
) -> AgentDocumentContentPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        document, content = agent_service.read_document_text(agent, document_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _document_content_payload(document, content)


@app.post("/agents/{agent_id}/tools/analyze-url", response_model=AgentWebAnalysisPayload)
def analyze_agent_web_url(
    agent_id: str,
    payload: AgentWebAnalysisRequestPayload,
    authorization: str | None = Header(default=None),
) -> AgentWebAnalysisPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        analysis = AgentToolset.analyze_web_url(
            url=payload.url,
            timeout_seconds=payload.timeout_seconds,
            max_chars=payload.max_chars,
            max_points=payload.max_points,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AgentWebAnalysisPayload(**analysis)


@app.post("/agents/{agent_id}/documents", response_model=AgentDocumentPayload)
async def upload_agent_document(
    agent_id: str,
    file: UploadFile = File(...),
    operational_section: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
) -> AgentDocumentPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    content = await file.read()

    try:
        document = agent_service.save_document(
            agent=agent,
            filename=file.filename or "",
            content=content,
            operational_section=operational_section,
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _document_payload(document)


@app.delete("/agents/{agent_id}/documents/{document_id}")
def delete_agent_document(
    agent_id: str,
    document_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        agent_service.delete_document(agent=agent, document_id=document_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"status": "deleted", "document_id": document_id}


@app.post("/agents/{agent_id}/index/rebuild", response_model=AgentIndexPayload)
def rebuild_agent_index(
    agent_id: str,
    authorization: str | None = Header(default=None),
) -> AgentIndexPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}
    logger.info(
        "api_agent_index_rebuild_request user_id=%s agent_id=%s",
        principal.user_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        index_result = agent_service.rebuild_index(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning(
            "api_agent_index_rebuild_failed user_id=%s agent_id=%s detail=%s",
            principal.user_id,
            agent_id,
            exc,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    logger.info(
        (
            "api_agent_index_rebuild_ok user_id=%s agent_id=%s backend=%s "
            "documents=%s chunks=%s"
        ),
        principal.user_id,
        agent.agent_id,
        index_result.backend,
        index_result.total_documents,
        index_result.total_chunks,
    )
    return AgentIndexPayload(
        agent_id=agent.agent_id,
        backend=index_result.backend,
        total_documents=index_result.total_documents,
        total_chunks=index_result.total_chunks,
        companies=index_result.companies,
        index_path=str(index_result.index_path),
    )


@app.get("/agents/{agent_id}/index/status", response_model=AgentIndexStatusPayload)
def get_agent_index_status(
    agent_id: str,
    authorization: str | None = Header(default=None),
) -> AgentIndexStatusPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    documents = agent_service.list_documents(agent.agent_id)
    indexed = [document for document in documents if document.status == "indexed"]
    failed = [document for document in documents if document.status == "failed"]
    uploaded = [document for document in documents if document.status == "uploaded"]
    last_error = failed[0].error_message if failed else None

    return AgentIndexStatusPayload(
        agent_id=agent.agent_id,
        has_index=Path(agent.index_path).exists(),
        indexed_at=agent.indexed_at.isoformat() if agent.indexed_at else None,
        documents_total=len(documents),
        documents_indexed=len(indexed),
        documents_failed=len(failed),
        documents_uploaded=len(uploaded),
        last_error=last_error,
    )


@app.get("/agents/{agent_id}/setup-status", response_model=AgentSetupStatusPayload)
def get_agent_setup_status(
    agent_id: str,
    authorization: str | None = Header(default=None),
) -> AgentSetupStatusPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    documents = agent_service.list_documents(agent.agent_id)
    documents_indexed = len([doc for doc in documents if doc.status == "indexed"])
    index_ready = Path(agent.index_path).exists() and documents_indexed > 0

    test_messages = 0
    if chat_audit_service is not None:
        try:
            rows = chat_audit_service.summary(company_id=agent.company_id, since_days=60)
            for row in rows:
                if row.agent_id == agent.agent_id:
                    test_messages = row.assistant_messages
                    break
        except Exception as exc:
            logger.warning("setup_status_audit_read_failed agent_id=%s detail=%s", agent.agent_id, exc)

    whatsapp_ready = False
    try:
        whatsapp_config = agent_service.get_whatsapp_channel_config(agent)
        whatsapp_ready = _is_agent_whatsapp_config_ready(whatsapp_config)
    except AgentValidationError:
        whatsapp_ready = False

    webchat_ready = True
    try:
        _public_widget_token(agent.agent_id, agent.company_id)
    except RuntimeError:
        webchat_ready = False

    steps = [
        AgentSetupStepPayload(
            id="agent",
            label="Crear agente",
            description="Agente base creado con company_id y objetivos iniciales.",
            ready=True,
            href=f"/agents/{agent.agent_id}/setup",
        ),
        AgentSetupStepPayload(
            id="knowledge",
            label="Cargar conocimiento",
            description="Sube documentos o bloques operativos para construir contexto.",
            ready=len(documents) > 0,
            href=f"/agents/{agent.agent_id}/knowledge/new?section=facts",
        ),
        AgentSetupStepPayload(
            id="tests",
            label="Probar respuestas",
            description="Valida el comportamiento en pruebas antes de publicar.",
            ready=test_messages > 0,
            href=f"/agents/{agent.agent_id}/playground",
        ),
        AgentSetupStepPayload(
            id="channel",
            label="Conectar canal",
            description="Activa WhatsApp o webchat y valida configuracion.",
            ready=whatsapp_ready or webchat_ready,
            href=f"/agents/{agent.agent_id}/deploy",
        ),
    ]

    completed = len([step for step in steps if step.ready])
    progress_percent = int(round((completed / len(steps)) * 100))
    next_href = next((step.href for step in steps if not step.ready), None)

    return AgentSetupStatusPayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        agent_name=agent.name,
        rag_backend=agent.rag_backend,
        progress_percent=progress_percent,
        ready_to_publish=all(step.ready for step in steps),
        next_href=next_href,
        documents_total=len(documents),
        documents_indexed=documents_indexed,
        test_messages=test_messages,
        steps=steps,
    )


@app.get("/internal/ai/agents/{agent_id}/setup-status", response_model=AgentSetupStatusPayload)
def internal_get_agent_setup_status(
    agent_id: str,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> AgentSetupStatusPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_setup_status request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    documents = agent_service.list_documents(agent.agent_id)
    documents_indexed = len([doc for doc in documents if doc.status == "indexed"])

    test_messages = 0
    if chat_audit_service is not None:
        try:
            rows = chat_audit_service.summary(company_id=agent.company_id, since_days=60)
            for row in rows:
                if row.agent_id == agent.agent_id:
                    test_messages = row.assistant_messages
                    break
        except Exception as exc:
            logger.warning("internal_setup_status_audit_read_failed agent_id=%s detail=%s", agent.agent_id, exc)

    whatsapp_ready = False
    try:
        whatsapp_config = agent_service.get_whatsapp_channel_config(agent)
        whatsapp_ready = _is_agent_whatsapp_config_ready(whatsapp_config)
    except AgentValidationError:
        whatsapp_ready = False

    webchat_ready = True
    try:
        _public_widget_token(agent.agent_id, agent.company_id)
    except RuntimeError:
        webchat_ready = False

    steps = [
        AgentSetupStepPayload(
            id="agent",
            label="Crear agente",
            description="Agente base creado con company_id y objetivos iniciales.",
            ready=True,
            href=f"/agents/{agent.agent_id}/setup",
        ),
        AgentSetupStepPayload(
            id="knowledge",
            label="Cargar conocimiento",
            description="Sube documentos o bloques operativos para construir contexto.",
            ready=len(documents) > 0,
            href=f"/agents/{agent.agent_id}/knowledge/new?section=facts",
        ),
        AgentSetupStepPayload(
            id="tests",
            label="Probar respuestas",
            description="Valida el comportamiento en pruebas antes de publicar.",
            ready=test_messages > 0,
            href=f"/agents/{agent.agent_id}/playground",
        ),
        AgentSetupStepPayload(
            id="channel",
            label="Conectar canal",
            description="Activa WhatsApp o webchat y valida configuracion.",
            ready=whatsapp_ready or webchat_ready,
            href=f"/agents/{agent.agent_id}/deploy",
        ),
    ]

    completed = len([step for step in steps if step.ready])
    progress_percent = int(round((completed / len(steps)) * 100))
    next_href = next((step.href for step in steps if not step.ready), None)

    return AgentSetupStatusPayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        agent_name=agent.name,
        rag_backend=agent.rag_backend,
        progress_percent=progress_percent,
        ready_to_publish=all(step.ready for step in steps),
        next_href=next_href,
        documents_total=len(documents),
        documents_indexed=documents_indexed,
        test_messages=test_messages,
        steps=steps,
    )


@app.post("/agents/{agent_id}/feedback", response_model=AgentFeedbackSummaryPayload)
def create_agent_feedback(
    agent_id: str,
    payload: AgentFeedbackCreatePayload,
    authorization: str | None = Header(default=None),
) -> AgentFeedbackSummaryPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    rating = payload.rating.strip().lower()
    if rating not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="rating debe ser 'up' o 'down'")

    if agent_feedback_service is not None:
        agent_feedback_service.record(
            AgentFeedbackRecord(
                company_id=agent.company_id,
                agent_id=agent.agent_id,
                rating=rating,
                question=payload.question,
                answer=payload.answer,
                sources=payload.sources,
                comment=payload.comment,
                expected_answer=payload.expected_answer,
                session_id=payload.session_id,
                source_channel=payload.source_channel or "agent_dashboard",
            )
        )

    summary = (
        agent_feedback_service.summary(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            since_days=30,
        )
        if agent_feedback_service is not None
        else AgentFeedbackSummary(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            feedback_total=0,
            thumbs_up=0,
            thumbs_down=0,
            positive_rate=0.0,
            with_comment=0,
            with_expected_answer=0,
        )
    )

    return _to_agent_feedback_summary_payload(summary)


@app.get("/agents/{agent_id}/feedback/summary", response_model=AgentFeedbackSummaryPayload)
def get_agent_feedback_summary(
    agent_id: str,
    authorization: str | None = Header(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> AgentFeedbackSummaryPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    summary = (
        agent_feedback_service.summary(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            since_days=days,
        )
        if agent_feedback_service is not None
        else AgentFeedbackSummary(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            feedback_total=0,
            thumbs_up=0,
            thumbs_down=0,
            positive_rate=0.0,
            with_comment=0,
            with_expected_answer=0,
        )
    )
    return _to_agent_feedback_summary_payload(summary)


@app.get("/internal/ai/agents/{agent_id}/feedback/summary", response_model=AgentFeedbackSummaryPayload)
def internal_get_agent_feedback_summary(
    agent_id: str,
    days: int = Query(default=30, ge=1, le=365),
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> AgentFeedbackSummaryPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_feedback_summary request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    summary = (
        agent_feedback_service.summary(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            since_days=days,
        )
        if agent_feedback_service is not None
        else AgentFeedbackSummary(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            feedback_total=0,
            thumbs_up=0,
            thumbs_down=0,
            positive_rate=0.0,
            with_comment=0,
            with_expected_answer=0,
        )
    )

    return _to_agent_feedback_summary_payload(summary)


@app.post("/internal/ai/agents/{agent_id}/chat", response_model=AgentChatResponsePayload)
def internal_chat_with_agent(
    agent_id: str,
    payload: AgentChatRequestPayload,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> AgentChatResponsePayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )
    allowed_org_ids = {org_id}
    started = time.perf_counter()

    logger.info(
        (
            "internal_agent_chat_request request_id=%s user_id=%s agent_id=%s "
            "company_id=%s org_id=%s top_k=%s"
        ),
        request_id,
        user_id,
        agent_id,
        company_id,
        org_id,
        payload.top_k,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")

        effective_session_id = payload.session_id or user_id
        chat_channel = _effective_chat_channel(payload.channel, "api_internal")
        clubhx_tools_client = _get_clubhx_tools_client()
        role_context = build_role_context(agent=agent, channel=chat_channel)
        summary_context = _agent_summary_context(agent.company_id, agent.agent_id, effective_session_id)
        workflow_state = _agent_workflow_state(agent.company_id, agent.agent_id, effective_session_id)
        shared_commerce_payload = _resolve_shared_commerce_payload(
            company_id=agent.company_id,
            user_id=user_id,
            session_id=effective_session_id,
            message=payload.message,
            channel=chat_channel,
            clubhx_tools_client=clubhx_tools_client,
            intent_label=None,
            response_style_context=(
                f"objective={role_context.objective}\n"
                f"tone={role_context.tone}\n"
                f"rules={role_context.system_rules}\n"
                f"summary={summary_context}"
            ),
            workflow_state=workflow_state,
        )
        if shared_commerce_payload:
            shared_products = shared_commerce_payload.get("products") if isinstance(shared_commerce_payload.get("products"), list) else None
            if shared_products:
                _remember_commerce_products(effective_session_id, shared_products)
            shared_answer = enforce_channel_response_contract(
                str(shared_commerce_payload.get("answer") or "").strip(),
                query=payload.message,
                channel=chat_channel,
            )
            if shared_answer:
                _update_agent_memory_from_payload(
                    agent_id=agent.agent_id,
                    company_id=agent.company_id,
                    session_id=effective_session_id,
                    user_message=payload.message,
                    answer=shared_answer,
                    payload=shared_commerce_payload,
                )
                return AgentChatResponsePayload(
                    agent_id=agent.agent_id,
                    company_id=agent.company_id,
                    session_id=effective_session_id,
                    answer=shared_answer,
                    sources=[],
                    intent_label=str((shared_commerce_payload.get("intent_label") or "commerce")).strip() or "commerce",
                    route="tool",
                    route_reason="shared_commerce",
                    response_mode="tool_only",
                    fallback_applied=False,
                    retrieval_min_score=None,
                    redirect_to=str(shared_commerce_payload.get("redirect_to") or "").strip() or None,
                    workflow_action=shared_commerce_payload.get("workflow_action") if isinstance(shared_commerce_payload.get("workflow_action"), dict) else None,
                    cart_action=shared_commerce_payload.get("cart_action") if isinstance(shared_commerce_payload.get("cart_action"), dict) else None,
                    cart_actions=shared_commerce_payload.get("cart_actions") if isinstance(shared_commerce_payload.get("cart_actions"), list) else None,
                    products=shared_products,
                )
        rag_result = agent_service.chat(
            agent=agent,
            message=payload.message,
            company_id=agent.company_id,
            top_k=payload.top_k,
            session_id=effective_session_id,
            external_user_id=user_id,
            channel=chat_channel,
            use_openai=payload.use_openai_generation,
            generation_provider=payload.generation_provider,
            generation_model=payload.generation_model,
        )

        routed_tool = _tool_for_intent(rag_result.intent_label or "", payload.message, effective_session_id)
        if not routed_tool and rag_result.route == "no_knowledge":
            routed_tool = _forced_commerce_tool(payload.message, effective_session_id)
        logger.info(
            "internal_agent_chat_tool_routing request_id=%s intent=%s route=%s routed_tool=%s client_ready=%s",
            request_id,
            rag_result.intent_label,
            rag_result.route,
            routed_tool[0] if routed_tool else None,
            bool(clubhx_tools_client),
        )
        if clubhx_tools_client and routed_tool:
            try:
                canonical = clubhx_tools_client.execute_canonical(
                    tenant_id=agent.company_id,
                    tool=routed_tool[0],
                    channel=chat_channel,
                    user_id=user_id,
                    arguments=routed_tool[1],
                )
                tool_payload = _format_public_widget_tool_payload(
                    canonical,
                    user_message=payload.message,
                    intent_label=rag_result.intent_label,
                    channel=chat_channel,
                    session_id=effective_session_id,
                )
                tool_products = (tool_payload or {}).get("products") if isinstance((tool_payload or {}).get("products"), list) else None
                if tool_products:
                    _remember_commerce_products(effective_session_id, tool_products)
                tool_answer = enforce_channel_response_contract(
                    str((tool_payload or {}).get("answer") or "").strip(),
                    query=payload.message,
                    channel=chat_channel,
                )
                if tool_answer:
                    _update_agent_memory_from_payload(
                        agent_id=agent.agent_id,
                        company_id=agent.company_id,
                        session_id=effective_session_id,
                        user_message=payload.message,
                        answer=tool_answer,
                        payload=tool_payload,
                        fallback_intent=rag_result.intent_label,
                        fallback_tool=routed_tool[0],
                    )
                    return AgentChatResponsePayload(
                        agent_id=agent.agent_id,
                        company_id=agent.company_id,
                        session_id=effective_session_id,
                        answer=tool_answer,
                        sources=[],
                        intent_label=rag_result.intent_label,
                        route="tool",
                        route_reason="canonical_tool",
                        response_mode="tool_only",
                        fallback_applied=False,
                        retrieval_min_score=None,
                        redirect_to=str((tool_payload or {}).get("redirect_to") or "").strip() or None,
                        workflow_action=(tool_payload or {}).get("workflow_action") if isinstance((tool_payload or {}).get("workflow_action"), dict) else None,
                        cart_action=(tool_payload or {}).get("cart_action") if isinstance((tool_payload or {}).get("cart_action"), dict) else None,
                        cart_actions=(tool_payload or {}).get("cart_actions") if isinstance((tool_payload or {}).get("cart_actions"), list) else None,
                        products=(tool_payload or {}).get("products") if isinstance((tool_payload or {}).get("products"), list) else None,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "agent_tool_route_failed request_id=%s tool=%s detail=%s",
                    request_id,
                    routed_tool[0],
                    exc,
                )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning(
            "internal_agent_chat_failed request_id=%s user_id=%s agent_id=%s detail=%s",
            request_id,
            user_id,
            agent_id,
            exc,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if rag_result.response_mode in {"repeat_cached", "repeat_generic", "conversation_closed"}:
        tuned_answer = rag_result.answer
    else:
        final_rag_answer = _personalize_agent_freeform_response(
            agent_name=agent.name,
            company_id=agent.company_id,
            message=payload.message,
            route=rag_result.route,
            default_answer=rag_result.answer,
        )
        tuned_answer = enforce_channel_response_contract(
            tune_answer_style(final_rag_answer, query=payload.message),
            query=payload.message,
            channel=chat_channel,
        )

    response_latency_ms = int((time.perf_counter() - started) * 1000)
    _record_chat_audit(
        ChatAuditRecord(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            session_id=effective_session_id,
            channel="platform_api_proxy",
            user_message=payload.message,
            assistant_message=tuned_answer,
            intent_label=rag_result.intent_label,
            route=rag_result.route,
            response_mode=rag_result.response_mode,
            sources_count=len(rag_result.sources),
            used_llm=bool(
                payload.use_openai_generation
                if payload.use_openai_generation is not None
                else agent.use_openai_generation
            ),
            cached_response=rag_result.response_mode == "repeat_cached",
            latency_ms=response_latency_ms,
            authenticated_user_id=user_id,
            external_user_id=user_id,
        )
    )
    retrieval_scores = [chunk.score for chunk in rag_result.retrieved_chunks]
    average_retrieval_score = (
        sum(retrieval_scores) / len(retrieval_scores) if retrieval_scores else None
    )
    max_retrieval_score = max(retrieval_scores) if retrieval_scores else None
    _record_retrieval_audit(
        RetrievalAuditRecord(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            channel="platform_api_proxy",
            route=rag_result.route,
            response_mode=rag_result.response_mode,
            retrieved_chunks=len(rag_result.retrieved_chunks),
            sources_count=len(rag_result.sources),
            avg_retrieval_score=average_retrieval_score,
            max_retrieval_score=max_retrieval_score,
            min_score_threshold=rag_result.retrieval_min_score,
            fallback_applied=bool(rag_result.fallback_applied),
            latency_ms=response_latency_ms,
            rag_backend=agent.rag_backend,
        )
    )

    return AgentChatResponsePayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        session_id=effective_session_id,
        answer=tuned_answer,
        sources=rag_result.sources,
        intent_label=rag_result.intent_label,
        route=rag_result.route,
        route_reason=rag_result.route_reason,
        response_mode=rag_result.response_mode,
        fallback_applied=rag_result.fallback_applied,
        retrieval_min_score=(min(retrieval_scores) if retrieval_scores else None),
    )


@app.post("/internal/ai/media/transcriptions", response_model=MediaTranscriptionPayload)
def internal_transcribe_media(
    payload: MediaTranscriptionRequestPayload,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> MediaTranscriptionPayload:
    logger.info(
        "[transcribe] internal_request company_id=%s org_id=%s user_id=%s request_id=%s has_file=%s mime_type=%s language_hint=%s",
        x_company_id or "",
        x_org_id or "",
        x_user_id or "",
        x_request_id or "",
        bool(payload.content_base64),
        payload.mime_type or "",
        payload.language_hint or "",
    )
    _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    try:
        audio_bytes = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="content_base64 invalido") from exc

    result = _transcribe_audio_bytes(
        audio_bytes=audio_bytes,
        filename=payload.filename,
        mime_type=payload.mime_type,
        language_hint=payload.language_hint,
    )
    if result is None:
        logger.warning(
            "[transcribe] internal_no_result company_id=%s org_id=%s request_id=%s",
            x_company_id or "",
            x_org_id or "",
            x_request_id or "",
        )
        raise HTTPException(status_code=503, detail="Servicio de transcripcion no disponible")
    logger.info(
        "[transcribe] internal_ok company_id=%s org_id=%s request_id=%s text_len=%s",
        x_company_id or "",
        x_org_id or "",
        x_request_id or "",
        len(result.text),
    )
    return result


@app.post("/agents/{agent_id}/chat", response_model=AgentChatResponsePayload)
def chat_with_agent(
    agent_id: str,
    payload: AgentChatRequestPayload,
    authorization: str | None = Header(default=None),
) -> AgentChatResponsePayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}
    logger.info(
        (
            "api_agent_chat_request user_id=%s agent_id=%s top_k=%s use_llm=%s "
            "provider_override=%s model_override=%s"
        ),
        principal.user_id,
        agent_id,
        payload.top_k,
        payload.use_openai_generation,
        payload.generation_provider,
        payload.generation_model,
    )
    started = time.perf_counter()

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        effective_session_id = payload.session_id or principal.user_id
        chat_channel = _effective_chat_channel(payload.channel, "api")
        clubhx_tools_client = _get_clubhx_tools_client()
        role_context = build_role_context(agent=agent, channel=chat_channel)
        summary_context = _agent_summary_context(agent.company_id, agent.agent_id, effective_session_id)
        workflow_state = _agent_workflow_state(agent.company_id, agent.agent_id, effective_session_id)
        shared_commerce_payload = _resolve_shared_commerce_payload(
            company_id=agent.company_id,
            user_id=principal.user_id,
            session_id=effective_session_id,
            message=payload.message,
            channel=chat_channel,
            clubhx_tools_client=clubhx_tools_client,
            intent_label=None,
            response_style_context=(
                f"objective={role_context.objective}\n"
                f"tone={role_context.tone}\n"
                f"rules={role_context.system_rules}\n"
                f"summary={summary_context}"
            ),
            workflow_state=workflow_state,
        )
        if shared_commerce_payload:
            shared_products = shared_commerce_payload.get("products") if isinstance(shared_commerce_payload.get("products"), list) else None
            if shared_products:
                _remember_commerce_products(effective_session_id, shared_products)
            shared_answer = enforce_channel_response_contract(
                str(shared_commerce_payload.get("answer") or "").strip(),
                query=payload.message,
                channel=chat_channel,
            )
            if shared_answer:
                _update_agent_memory_from_payload(
                    agent_id=agent.agent_id,
                    company_id=agent.company_id,
                    session_id=effective_session_id,
                    user_message=payload.message,
                    answer=shared_answer,
                    payload=shared_commerce_payload,
                )
                return AgentChatResponsePayload(
                    agent_id=agent.agent_id,
                    company_id=agent.company_id,
                    session_id=effective_session_id,
                    answer=shared_answer,
                    sources=[],
                    intent_label=str((shared_commerce_payload.get("intent_label") or "commerce")).strip() or "commerce",
                    route="tool",
                    route_reason="shared_commerce",
                    response_mode="tool_only",
                    fallback_applied=False,
                    retrieval_min_score=None,
                    redirect_to=str(shared_commerce_payload.get("redirect_to") or "").strip() or None,
                    workflow_action=shared_commerce_payload.get("workflow_action") if isinstance(shared_commerce_payload.get("workflow_action"), dict) else None,
                    cart_action=shared_commerce_payload.get("cart_action") if isinstance(shared_commerce_payload.get("cart_action"), dict) else None,
                    cart_actions=shared_commerce_payload.get("cart_actions") if isinstance(shared_commerce_payload.get("cart_actions"), list) else None,
                    products=shared_products,
                )
        rag_result = agent_service.chat(
            agent=agent,
            message=payload.message,
            company_id=agent.company_id,
            top_k=payload.top_k,
            session_id=effective_session_id,
            external_user_id=principal.user_id,
            channel=chat_channel,
            use_openai=payload.use_openai_generation,
            generation_provider=payload.generation_provider,
            generation_model=payload.generation_model,
        )

        routed_tool = _tool_for_intent(rag_result.intent_label or "", payload.message, effective_session_id)
        if not routed_tool and rag_result.route == "no_knowledge":
            routed_tool = _forced_commerce_tool(payload.message, effective_session_id)
        logger.info(
            "api_agent_chat_tool_routing user_id=%s intent=%s route=%s routed_tool=%s client_ready=%s",
            principal.user_id,
            rag_result.intent_label,
            rag_result.route,
            routed_tool[0] if routed_tool else None,
            bool(clubhx_tools_client),
        )
        if clubhx_tools_client and routed_tool:
            try:
                canonical = clubhx_tools_client.execute_canonical(
                    tenant_id=agent.company_id,
                    tool=routed_tool[0],
                    channel=chat_channel,
                    user_id=principal.user_id,
                    arguments=routed_tool[1],
                )
                tool_payload = _format_public_widget_tool_payload(
                    canonical,
                    user_message=payload.message,
                    intent_label=rag_result.intent_label,
                    channel=chat_channel,
                    session_id=effective_session_id,
                )
                tool_products = (tool_payload or {}).get("products") if isinstance((tool_payload or {}).get("products"), list) else None
                if tool_products:
                    _remember_commerce_products(effective_session_id, tool_products)
                tool_answer = enforce_channel_response_contract(
                    str((tool_payload or {}).get("answer") or "").strip(),
                    query=payload.message,
                    channel=chat_channel,
                )
                if tool_answer:
                    _update_agent_memory_from_payload(
                        agent_id=agent.agent_id,
                        company_id=agent.company_id,
                        session_id=effective_session_id,
                        user_message=payload.message,
                        answer=tool_answer,
                        payload=tool_payload,
                        fallback_intent=rag_result.intent_label,
                        fallback_tool=routed_tool[0],
                    )
                    return AgentChatResponsePayload(
                        agent_id=agent.agent_id,
                        company_id=agent.company_id,
                        session_id=effective_session_id,
                        answer=tool_answer,
                        sources=[],
                        intent_label=rag_result.intent_label,
                        route="tool",
                        route_reason="canonical_tool",
                        response_mode="tool_only",
                        fallback_applied=False,
                        retrieval_min_score=None,
                        redirect_to=str((tool_payload or {}).get("redirect_to") or "").strip() or None,
                        workflow_action=(tool_payload or {}).get("workflow_action") if isinstance((tool_payload or {}).get("workflow_action"), dict) else None,
                        cart_action=(tool_payload or {}).get("cart_action") if isinstance((tool_payload or {}).get("cart_action"), dict) else None,
                        cart_actions=(tool_payload or {}).get("cart_actions") if isinstance((tool_payload or {}).get("cart_actions"), list) else None,
                        products=(tool_payload or {}).get("products") if isinstance((tool_payload or {}).get("products"), list) else None,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "agent_tool_route_failed user_id=%s tool=%s detail=%s",
                    principal.user_id,
                    routed_tool[0],
                    exc,
                )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning(
            "api_agent_chat_failed user_id=%s agent_id=%s detail=%s",
            principal.user_id,
            agent_id,
            exc,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if rag_result.response_mode in {"repeat_cached", "repeat_generic", "conversation_closed"}:
        tuned_answer = rag_result.answer
    else:
        final_rag_answer = _personalize_agent_freeform_response(
            agent_name=agent.name,
            company_id=agent.company_id,
            message=payload.message,
            route=rag_result.route,
            default_answer=rag_result.answer,
        )
        tuned_answer = enforce_channel_response_contract(
            tune_answer_style(final_rag_answer, query=payload.message),
            query=payload.message,
            channel=chat_channel,
        )
    logger.info(
        "api_agent_chat_ok user_id=%s agent_id=%s company_id=%s sources=%s answer_chars=%s",
        principal.user_id,
        agent.agent_id,
        agent.company_id,
        len(rag_result.sources),
        len(tuned_answer),
    )
    response_latency_ms = int((time.perf_counter() - started) * 1000)
    _record_chat_audit(
        ChatAuditRecord(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            session_id=effective_session_id,
            channel="agent_dashboard",
            user_message=payload.message,
            assistant_message=tuned_answer,
            intent_label=rag_result.intent_label,
            route=rag_result.route,
            response_mode=rag_result.response_mode,
            sources_count=len(rag_result.sources),
            used_llm=bool(
                payload.use_openai_generation
                if payload.use_openai_generation is not None
                else agent.use_openai_generation
            ),
            cached_response=rag_result.response_mode == "repeat_cached",
            latency_ms=response_latency_ms,
            authenticated_user_id=principal.user_id,
            external_user_id=principal.user_id,
        )
    )
    retrieval_scores = [chunk.score for chunk in rag_result.retrieved_chunks]
    average_retrieval_score = (
        sum(retrieval_scores) / len(retrieval_scores) if retrieval_scores else None
    )
    max_retrieval_score = max(retrieval_scores) if retrieval_scores else None
    _record_retrieval_audit(
        RetrievalAuditRecord(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            channel="agent_dashboard",
            route=rag_result.route,
            response_mode=rag_result.response_mode,
            retrieved_chunks=len(rag_result.retrieved_chunks),
            sources_count=len(rag_result.sources),
            avg_retrieval_score=average_retrieval_score,
            max_retrieval_score=max_retrieval_score,
            min_score_threshold=rag_result.retrieval_min_score,
            fallback_applied=bool(rag_result.fallback_applied),
            latency_ms=response_latency_ms,
            rag_backend=agent.rag_backend,
        )
    )
    return AgentChatResponsePayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        session_id=effective_session_id,
        answer=tuned_answer,
        sources=rag_result.sources,
        intent_label=rag_result.intent_label,
        route=rag_result.route,
        route_reason=rag_result.route_reason,
        response_mode=rag_result.response_mode,
        fallback_applied=rag_result.fallback_applied,
        retrieval_min_score=rag_result.retrieval_min_score,
    )


@app.post(
    "/internal/ai/runtime/skills/{skill_id}/execute",
    response_model=InternalRuntimeExecuteResponsePayload,
)
def internal_execute_published_skill(
    skill_id: str,
    payload: InternalRuntimeExecuteRequestPayload,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> InternalRuntimeExecuteResponsePayload:
    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_runtime_skill_execute request_id=%s user_id=%s org_id=%s company_id=%s skill_id=%s version=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        skill_id,
        payload.version,
    )

    return InternalRuntimeExecuteResponsePayload(
        execution_id=str(uuid4()),
        type="skill",
        id=skill_id,
        version=payload.version,
        status="accepted",
        output={
            "company_id": company_id,
            "org_id": org_id,
            "user_id": user_id,
            "echo": payload.input or {},
            "runtime": "stub",
        },
    )


@app.post(
    "/internal/ai/runtime/flows/{flow_id}/execute",
    response_model=InternalRuntimeExecuteResponsePayload,
)
def internal_execute_published_flow(
    flow_id: str,
    payload: InternalRuntimeExecuteRequestPayload,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
) -> InternalRuntimeExecuteResponsePayload:
    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_runtime_flow_execute request_id=%s user_id=%s org_id=%s company_id=%s flow_id=%s version=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        flow_id,
        payload.version,
    )

    return InternalRuntimeExecuteResponsePayload(
        execution_id=str(uuid4()),
        type="flow",
        id=flow_id,
        version=payload.version,
        status="accepted",
        output={
            "company_id": company_id,
            "org_id": org_id,
            "user_id": user_id,
            "echo": payload.input or {},
            "runtime": "stub",
        },
    )


@app.get("/internal/ai/agents/{agent_id}/widget-config", response_model=AgentWidgetConfigPayload)
def internal_get_agent_widget_config(
    agent_id: str,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
    x_public_base_url: str | None = Header(default=None, alias="X-Public-Base-Url"),
) -> AgentWidgetConfigPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_widget_config request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
        widget_token = _public_widget_token(agent.agent_id, agent.company_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    api_base_url = _public_widget_api_base_url_internal(x_public_base_url)
    snippet = _public_widget_snippet(
        api_base_url=api_base_url,
        widget_id=agent.agent_id,
        widget_token=widget_token,
    )
    return AgentWidgetConfigPayload(
        agent_id=agent.agent_id,
        widget_id=agent.agent_id,
        endpoint_url=f"{api_base_url}/public/widget/chat",
        widget_token=widget_token,
        allowed_origins=_public_widget_allowed_origins(),
        rate_limit_window_seconds=_public_widget_rate_limit_window_seconds(),
        rate_limit_max_requests=_public_widget_rate_limit_max_requests(),
        snippet_html=snippet,
    )


@app.get("/internal/ai/agents/{agent_id}/channels/whatsapp/config", response_model=AgentWhatsAppConfigPayload)
def internal_get_agent_whatsapp_config(
    agent_id: str,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
    x_public_base_url: str | None = Header(default=None, alias="X-Public-Base-Url"),
) -> AgentWhatsAppConfigPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_whatsapp_get_config request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
        config = agent_service.get_whatsapp_channel_config(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _whatsapp_config_payload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        webhook_url=_whatsapp_webhook_url_internal(x_public_base_url),
        config=config,
    )


@app.put("/internal/ai/agents/{agent_id}/channels/whatsapp/config", response_model=AgentWhatsAppConfigPayload)
def internal_update_agent_whatsapp_config(
    agent_id: str,
    payload: AgentWhatsAppConfigUpdatePayload,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
    x_public_base_url: str | None = Header(default=None, alias="X-Public-Base-Url"),
) -> AgentWhatsAppConfigPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_whatsapp_update_config request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
        config = agent_service.update_whatsapp_channel_config(
            agent=agent,
            phone_number_id=payload.phone_number_id,
            business_account_id=payload.business_account_id,
            verify_token=payload.verify_token,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _whatsapp_config_payload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        webhook_url=_whatsapp_webhook_url_internal(x_public_base_url),
        config=config,
    )


@app.post("/internal/ai/agents/{agent_id}/channels/whatsapp/validate", response_model=AgentWhatsAppValidationPayload)
def internal_validate_agent_whatsapp_config(
    agent_id: str,
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    x_platform_signature: str | None = Header(default=None, alias="X-Platform-Signature"),
    x_platform_timestamp: str | None = Header(default=None, alias="X-Platform-Timestamp"),
    x_public_base_url: str | None = Header(default=None, alias="X-Public-Base-Url"),
) -> AgentWhatsAppValidationPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    company_id, org_id, user_id, request_id = _require_internal_context(
        x_company_id=x_company_id,
        x_org_id=x_org_id,
        x_user_id=x_user_id,
        x_request_id=x_request_id,
        x_platform_signature=x_platform_signature,
        x_platform_timestamp=x_platform_timestamp,
    )

    logger.info(
        "internal_whatsapp_validate request_id=%s user_id=%s org_id=%s company_id=%s agent_id=%s",
        request_id,
        user_id,
        org_id,
        company_id,
        agent_id,
    )

    try:
        agent = agent_service.get_accessible_agent(agent_id, {org_id})
        if agent.company_id != company_id:
            raise HTTPException(status_code=403, detail="company_id sin acceso al agente")
        config = agent_service.get_whatsapp_channel_config(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    phone_number_id = (config.get("phone_number_id") or "").strip()
    verify_token = (config.get("verify_token") or "").strip()
    has_phone_number_id = bool(phone_number_id)
    has_verify_token = bool(verify_token)
    server_has_access_token = True
    company_map_ready = True

    messages: list[str] = []
    if not has_phone_number_id:
        messages.append("Falta phone_number_id de Meta.")
    if not verify_token:
        messages.append("Falta verify token del canal.")
    if not messages:
        messages.append("Configuracion persistida en el AI Engine.")

    ready = has_phone_number_id and has_verify_token and server_has_access_token and company_map_ready

    return AgentWhatsAppValidationPayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        ready=ready,
        has_phone_number_id=has_phone_number_id,
        has_verify_token=has_verify_token,
        server_has_access_token=server_has_access_token,
        company_map_ready=company_map_ready,
        webhook_url="",
        messages=messages,
    )


@app.get("/agents/{agent_id}/widget-config", response_model=AgentWidgetConfigPayload)
def get_agent_widget_config(
    agent_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> AgentWidgetConfigPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        widget_token = _public_widget_token(agent.agent_id, agent.company_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    api_base_url = _public_widget_api_base_url(request)
    snippet = _public_widget_snippet(
        api_base_url=api_base_url,
        widget_id=agent.agent_id,
        widget_token=widget_token,
    )
    return AgentWidgetConfigPayload(
        agent_id=agent.agent_id,
        widget_id=agent.agent_id,
        endpoint_url=f"{api_base_url}/public/widget/chat",
        widget_token=widget_token,
        allowed_origins=_public_widget_allowed_origins(),
        rate_limit_window_seconds=_public_widget_rate_limit_window_seconds(),
        rate_limit_max_requests=_public_widget_rate_limit_max_requests(),
        snippet_html=snippet,
    )


@app.get("/agents/{agent_id}/channels/whatsapp/config", response_model=AgentWhatsAppConfigPayload)
def get_agent_whatsapp_config(
    agent_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> AgentWhatsAppConfigPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        config = agent_service.get_whatsapp_channel_config(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _whatsapp_config_payload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        webhook_url=_whatsapp_webhook_url(request),
        config=config,
    )


@app.put("/agents/{agent_id}/channels/whatsapp/config", response_model=AgentWhatsAppConfigPayload)
def update_agent_whatsapp_config(
    agent_id: str,
    payload: AgentWhatsAppConfigUpdatePayload,
    request: Request,
    authorization: str | None = Header(default=None),
) -> AgentWhatsAppConfigPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        config = agent_service.update_whatsapp_channel_config(
            agent=agent,
            phone_number_id=payload.phone_number_id,
            business_account_id=payload.business_account_id,
            verify_token=payload.verify_token,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _whatsapp_config_payload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        webhook_url=_whatsapp_webhook_url(request),
        config=config,
    )


@app.post("/agents/{agent_id}/channels/whatsapp/validate", response_model=AgentWhatsAppValidationPayload)
def validate_agent_whatsapp_config(
    agent_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> AgentWhatsAppValidationPayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")
    if tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")

    principal = _require_principal(authorization)
    memberships = tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}

    try:
        agent = agent_service.get_accessible_agent(agent_id, allowed_org_ids)
        config = agent_service.get_whatsapp_channel_config(agent)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    phone_number_id = (config.get("phone_number_id") or "").strip()
    verify_token = (config.get("verify_token") or "").strip()
    has_phone_number_id = bool(phone_number_id)
    has_verify_token = bool(verify_token)
    server_has_access_token = True
    company_map_ready = True

    messages: list[str] = []
    if not has_phone_number_id:
        messages.append("Falta phone_number_id de Meta.")
    if not verify_token:
        messages.append("Falta verify token del canal.")
    if not messages:
        messages.append("Configuracion persistida en el AI Engine.")

    ready = has_phone_number_id and has_verify_token and server_has_access_token and company_map_ready

    return AgentWhatsAppValidationPayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        ready=ready,
        has_phone_number_id=has_phone_number_id,
        has_verify_token=has_verify_token,
        server_has_access_token=server_has_access_token,
        company_map_ready=company_map_ready,
        webhook_url="",
        messages=messages,
    )


@app.post("/public/widget/chat", response_model=PublicWidgetChatResponsePayload)
def public_widget_chat(
    payload: PublicWidgetChatRequestPayload,
    request: Request,
) -> PublicWidgetChatResponsePayload:
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Agent service no disponible")

    origin = request.headers.get("origin")
    if not _public_widget_origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin no permitido para widget")

    agent = agent_service.repository.get_agent(payload.widget_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Widget no encontrado")

    expected_token = _public_widget_token(agent.agent_id, agent.company_id)
    if not hmac.compare_digest(payload.widget_token, expected_token):
        raise HTTPException(status_code=403, detail="widget_token invalido")

    client_id = _public_widget_client_id(request)
    retry_after = _public_widget_rate_limit_retry_after(
        widget_id=payload.widget_id,
        client_id=client_id,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Rate limit excedido para este widget",
            headers={"Retry-After": str(retry_after)},
        )

    effective_session_id = _public_widget_session_id(
        widget_id=payload.widget_id,
        session_id=payload.session_id,
    )
    _trace_route(
        "widget.entry",
        widget_id=payload.widget_id,
        session_id=effective_session_id,
        visitor_id=payload.visitor_id or "",
        external_user_id=payload.external_user_id or "",
        message=_normalize_widget_text(payload.message),
    )
    started = time.perf_counter()

    clubhx_tools_client = _get_clubhx_tools_client()
    role_context = build_role_context(agent=agent, channel="widget_public")
    summary_context = _agent_summary_context(agent.company_id, agent.agent_id, effective_session_id)
    workflow_state = _agent_workflow_state(agent.company_id, agent.agent_id, effective_session_id)
    shared_commerce_payload = _resolve_shared_commerce_payload(
        company_id=agent.company_id,
        user_id=payload.external_user_id or payload.visitor_id or client_id,
        session_id=effective_session_id,
        message=payload.message,
        channel="widget_public",
        clubhx_tools_client=clubhx_tools_client,
        intent_label=None,
        response_style_context=(
            f"objective={role_context.objective}\n"
            f"tone={role_context.tone}\n"
            f"rules={role_context.system_rules}\n"
            f"summary={summary_context}"
        ),
        workflow_state=workflow_state,
    )
    if shared_commerce_payload and shared_commerce_payload.get("answer"):
        _trace_route(
            "widget.reply_from_commerce",
            widget_id=payload.widget_id,
            session_id=effective_session_id,
            intent=str(shared_commerce_payload.get("intent_label") or ""),
            workflow_stage=str(shared_commerce_payload.get("workflow_stage") or ""),
            checkout_stage=str(shared_commerce_payload.get("checkout_stage") or ""),
        )
        shared_products = shared_commerce_payload.get("products") if isinstance(shared_commerce_payload.get("products"), list) else None
        if shared_products:
            _remember_commerce_products(effective_session_id, shared_products)
        final_answer = enforce_channel_response_contract(
            str(shared_commerce_payload.get("answer") or "").strip(),
            query=payload.message,
            channel="widget_public",
        )
        _update_agent_memory_from_payload(
            agent_id=agent.agent_id,
            company_id=agent.company_id,
            session_id=effective_session_id,
            user_message=payload.message,
            answer=final_answer,
            payload=shared_commerce_payload,
        )
        response_latency_ms = int((time.perf_counter() - started) * 1000)
        _record_chat_audit(
            ChatAuditRecord(
                company_id=agent.company_id,
                agent_id=agent.agent_id,
                session_id=effective_session_id,
                channel="widget_public",
                user_message=payload.message,
                assistant_message=final_answer,
                intent_label=str(shared_commerce_payload.get("intent_label") or "commerce"),
                route="tool",
                response_mode="tool_only",
                sources_count=0,
                used_llm=agent.use_openai_generation,
                cached_response=False,
                latency_ms=response_latency_ms,
                visitor_id=payload.visitor_id,
                external_user_id=payload.external_user_id,
            )
        )
        _record_retrieval_audit(
            RetrievalAuditRecord(
                company_id=agent.company_id,
                agent_id=agent.agent_id,
                channel="widget_public",
                route="tool",
                response_mode="tool_only",
                retrieved_chunks=0,
                sources_count=0,
                avg_retrieval_score=None,
                max_retrieval_score=None,
                min_score_threshold=None,
                fallback_applied=False,
                latency_ms=response_latency_ms,
                rag_backend=agent.rag_backend,
            )
        )
        return PublicWidgetChatResponsePayload(
            widget_id=payload.widget_id,
            session_id=effective_session_id,
            answer=final_answer,
            sources=[],
            route="tool",
            intent_label=str(shared_commerce_payload.get("intent_label") or "commerce"),
            response_mode="tool_only",
            redirect_to=str(shared_commerce_payload.get("redirect_to") or "").strip() or None,
            workflow_action=shared_commerce_payload.get("workflow_action") if isinstance(shared_commerce_payload.get("workflow_action"), dict) else None,
            cart_action=shared_commerce_payload.get("cart_action") if isinstance(shared_commerce_payload.get("cart_action"), dict) else None,
            cart_actions=shared_commerce_payload.get("cart_actions") if isinstance(shared_commerce_payload.get("cart_actions"), list) else None,
            products=shared_products,
        )

    try:
        rag_result = agent_service.chat(
            agent=agent,
            message=payload.message,
            company_id=agent.company_id,
            top_k=payload.top_k,
            session_id=effective_session_id,
            visitor_id=payload.visitor_id,
            external_user_id=payload.external_user_id,
            channel="widget_public",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    routed_tool = _tool_for_intent(
        rag_result.intent_label or "",
        payload.message,
        effective_session_id,
    )
    if not routed_tool and rag_result.route == "no_knowledge":
        routed_tool = _forced_commerce_tool(payload.message, effective_session_id)
    _trace_route(
        "widget.agent_result",
        widget_id=payload.widget_id,
        session_id=effective_session_id,
        route=str(rag_result.route or ""),
        intent=str(rag_result.intent_label or ""),
        response_mode=str(rag_result.response_mode or ""),
        routed_tool=routed_tool[0] if routed_tool else "",
    )
    logger.info(
        "public_widget_chat_tool_routing widget_id=%s intent=%s route=%s routed_tool=%s client_ready=%s",
        payload.widget_id,
        rag_result.intent_label,
        rag_result.route,
        routed_tool[0] if routed_tool else None,
        bool(clubhx_tools_client),
    )
    if clubhx_tools_client and routed_tool:
        try:
            canonical = clubhx_tools_client.execute_canonical(
                tenant_id=agent.company_id,
                tool=routed_tool[0],
                channel="widget_public",
                user_id=payload.external_user_id or payload.visitor_id or client_id,
                arguments=routed_tool[1],
            )
            tool_payload = _format_public_widget_tool_payload(
                canonical,
                user_message=payload.message,
                intent_label=rag_result.intent_label,
                channel="widget_public",
                session_id=effective_session_id,
            )
            tool_products = tool_payload.get("products") if isinstance(tool_payload.get("products"), list) else None
            if tool_products:
                _remember_commerce_products(effective_session_id, tool_products)
            if tool_payload and tool_payload.get("answer"):
                _trace_route(
                    "widget.reply_from_agent_tool",
                    widget_id=payload.widget_id,
                    session_id=effective_session_id,
                    tool=routed_tool[0],
                    intent=str(rag_result.intent_label or ""),
                )
                final_answer = enforce_channel_response_contract(
                    str(tool_payload.get("answer") or "").strip(),
                    query=payload.message,
                    channel="widget_public",
                )
                _update_agent_memory_from_payload(
                    agent_id=agent.agent_id,
                    company_id=agent.company_id,
                    session_id=effective_session_id,
                    user_message=payload.message,
                    answer=final_answer,
                    payload=tool_payload,
                    fallback_intent=rag_result.intent_label,
                    fallback_tool=routed_tool[0],
                )
                response_latency_ms = int((time.perf_counter() - started) * 1000)

                _record_chat_audit(
                    ChatAuditRecord(
                        company_id=agent.company_id,
                        agent_id=agent.agent_id,
                        session_id=effective_session_id,
                        channel="widget_public",
                        user_message=payload.message,
                        assistant_message=final_answer,
                        intent_label=rag_result.intent_label,
                        route="tool",
                        response_mode="tool_only",
                        sources_count=0,
                        used_llm=agent.use_openai_generation,
                        cached_response=False,
                        latency_ms=response_latency_ms,
                        visitor_id=payload.visitor_id,
                        external_user_id=payload.external_user_id,
                    )
                )
                _record_retrieval_audit(
                    RetrievalAuditRecord(
                        company_id=agent.company_id,
                        agent_id=agent.agent_id,
                        channel="widget_public",
                        route="tool",
                        response_mode="tool_only",
                        retrieved_chunks=len(rag_result.retrieved_chunks),
                        sources_count=0,
                        avg_retrieval_score=None,
                        max_retrieval_score=None,
                        min_score_threshold=rag_result.retrieval_min_score,
                        fallback_applied=False,
                        latency_ms=response_latency_ms,
                        rag_backend=agent.rag_backend,
                    )
                )

                return PublicWidgetChatResponsePayload(
                    widget_id=payload.widget_id,
                    session_id=effective_session_id,
                    answer=final_answer,
                    sources=[],
                    route="tool",
                    intent_label=rag_result.intent_label,
                    response_mode="tool_only",
                    redirect_to=str(tool_payload.get("redirect_to") or "").strip() or None,
                    workflow_action=tool_payload.get("workflow_action") if isinstance(tool_payload.get("workflow_action"), dict) else None,
                    cart_action=tool_payload.get("cart_action") if isinstance(tool_payload.get("cart_action"), dict) else None,
                    cart_actions=tool_payload.get("cart_actions") if isinstance(tool_payload.get("cart_actions"), list) else None,
                    products=tool_payload.get("products") if isinstance(tool_payload.get("products"), list) else None,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "public_widget_tool_route_failed widget_id=%s agent_id=%s tool=%s detail=%s",
                payload.widget_id,
                agent.agent_id,
                routed_tool[0],
                exc,
            )

    if rag_result.response_mode in {"repeat_cached", "repeat_generic", "conversation_closed"}:
        base_answer = _personalize_agent_freeform_response(
            agent_name=agent.name,
            company_id=agent.company_id,
            message=payload.message,
            route=rag_result.route,
            default_answer=rag_result.answer,
        )
        final_answer = enforce_channel_response_contract(
            base_answer,
            query=payload.message,
            channel="widget_public",
        )
    else:
        base_answer = _personalize_agent_freeform_response(
            agent_name=agent.name,
            company_id=agent.company_id,
            message=payload.message,
            route=rag_result.route,
            default_answer=rag_result.answer,
        )
        final_answer = enforce_channel_response_contract(
            tune_answer_style(base_answer, query=payload.message),
            query=payload.message,
            channel="widget_public",
        )
    _trace_route(
        "widget.reply_from_agent",
        widget_id=payload.widget_id,
        session_id=effective_session_id,
        route=str(rag_result.route or ""),
        intent=str(rag_result.intent_label or ""),
        response_mode=str(rag_result.response_mode or ""),
    )
    response_latency_ms = int((time.perf_counter() - started) * 1000)

    _record_chat_audit(
        ChatAuditRecord(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            session_id=effective_session_id,
            channel="widget_public",
            user_message=payload.message,
            assistant_message=final_answer,
            intent_label=rag_result.intent_label,
            route=rag_result.route,
            response_mode=rag_result.response_mode,
            sources_count=len(rag_result.sources),
            used_llm=agent.use_openai_generation,
            cached_response=rag_result.response_mode == "repeat_cached",
            latency_ms=response_latency_ms,
            visitor_id=payload.visitor_id,
            external_user_id=payload.external_user_id,
        )
    )
    retrieval_scores = [chunk.score for chunk in rag_result.retrieved_chunks]
    average_retrieval_score = (
        sum(retrieval_scores) / len(retrieval_scores) if retrieval_scores else None
    )
    max_retrieval_score = max(retrieval_scores) if retrieval_scores else None
    _record_retrieval_audit(
        RetrievalAuditRecord(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            channel="widget_public",
            route=rag_result.route,
            response_mode=rag_result.response_mode,
            retrieved_chunks=len(rag_result.retrieved_chunks),
            sources_count=len(rag_result.sources),
            avg_retrieval_score=average_retrieval_score,
            max_retrieval_score=max_retrieval_score,
            min_score_threshold=rag_result.retrieval_min_score,
            fallback_applied=bool(rag_result.fallback_applied),
            latency_ms=response_latency_ms,
            rag_backend=agent.rag_backend,
        )
    )

    return PublicWidgetChatResponsePayload(
        widget_id=payload.widget_id,
        session_id=effective_session_id,
        answer=final_answer,
        sources=rag_result.sources,
        route=rag_result.route,
        intent_label=rag_result.intent_label,
        response_mode=rag_result.response_mode,
    )


@app.post("/chat", response_model=ChatResponsePayload)
def chat(
    payload: ChatRequestPayload,
    authorization: str | None = Header(default=None),
) -> ChatResponsePayload:
    if chat_service is None:
        raise HTTPException(status_code=503, detail=f"Servicio no disponible: {startup_error}")

    principal: AuthPrincipal | None = None
    if authorization:
        principal = _require_principal(authorization)
    elif not _chat_auth_compat_mode():
        raise HTTPException(status_code=401, detail="Este endpoint requiere autenticacion")

    requested_company_id = payload.company_id
    effective_company_id = requested_company_id
    effective_session_id = payload.session_id

    if principal is not None:
        if tenancy_service is None:
            raise HTTPException(status_code=503, detail="Tenancy no disponible")

        try:
            effective_company_id = tenancy_service.resolve_company_id(
                principal=principal,
                requested_company_id=requested_company_id,
            )
        except TenantContextError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except TenantForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        if not effective_session_id:
            effective_session_id = principal.user_id

    if not effective_company_id:
        raise HTTPException(status_code=400, detail="company_id es requerido")
    if not effective_session_id:
        raise HTTPException(status_code=400, detail="session_id es requerido")

    request = ChatRequest(
        company_id=effective_company_id,
        session_id=effective_session_id,
        message=payload.message,
        top_k=payload.top_k,
        generation_provider=payload.generation_provider,
        generation_model=payload.generation_model,
        use_openai_generation=payload.use_openai_generation,
    )
    try:
        result = chat_service.chat(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ChatResponsePayload(
        trace_id=result.trace_id,
        company_id=result.company_id,
        session_id=result.session_id,
        answer=enforce_channel_response_contract(
            tune_answer_style(result.answer, query=payload.message),
            query=payload.message,
            channel=payload.channel or "api",
        ),
        route=result.route,
        route_reason=result.route_reason,
        intent_label=result.intent_label,
        intent_confidence=result.intent_confidence,
        sources=result.sources,
        escalation_required=result.escalation_required,
        delivery_status=None,
        delivery_message_id=None,
        delivery_error=None,
    )
