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
import urllib.error
import urllib.request
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
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
from clasificacion_langchain.channels.idempotency import (
    InMemoryIdempotencyStore,
    RedisIdempotencyStore,
)
from clasificacion_langchain.channels.meta_whatsapp_api import MetaWhatsAppClient
from clasificacion_langchain.channels.whatsapp import parse_whatsapp_messages
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
from clasificacion_langchain.rag.generation import tune_answer_style
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


def _tool_for_intent(intent_label: str, message: str, session_id: str) -> tuple[str, dict[str, Any]] | None:
    label = (intent_label or "").strip().lower()
    message_text = (message or "").strip().lower()
    cart_request = _extract_widget_add_to_cart(message)
    if label in {"add_to_cart", "cart_add", "cart_update", "checkout_cart"} and cart_request:
        return "get_product_availability", {"query": cart_request["product_query"], "limit": 5, "session_id": session_id}
    if label in {"product_lookup", "catalog_query", "availability_check"}:
        return "get_product_availability", {"query": message, "limit": 5, "session_id": session_id}
    if label in {"delivery_quote", "shipping_options", "shipping_select"}:
        return "get_shipping_options", {"commune": message, "session_id": session_id}
    if label in {"payment_options", "payment_select", "checkout_payment"}:
        return "get_payment_options", {"session_id": session_id}
    if any(token in message_text for token in ["tienes ", "tienen ", "tenes ", "hay ", "busco ", "stock", "precio", "cuesta", "disponible"]):
        return "get_product_availability", {"query": message, "limit": 5, "session_id": session_id}
    if cart_request:
        return "get_product_availability", {"query": cart_request["product_query"], "limit": 5, "session_id": session_id}
    if any(token in message_text for token in ["despacho", "envio", "retiro", "chilexpress", "comuna"]):
        return "get_shipping_options", {"commune": message, "session_id": session_id}
    if any(token in message_text for token in ["pago", "pagar", "transferencia", "mercado pago", "tarjeta"]):
        return "get_payment_options", {"session_id": session_id}
    return None


def _forced_commerce_tool(message: str, session_id: str) -> tuple[str, dict[str, Any]] | None:
    text = (message or "").strip().lower()
    if not text:
        return None
    cart_request = _extract_widget_add_to_cart(message)
    if cart_request:
        logger.info(
            "forced_commerce_tool_match kind=add_to_cart session_id=%s message=%s product_query=%s quantity=%s",
            session_id,
            message,
            cart_request["product_query"],
            cart_request["quantity"],
        )
        return "get_product_availability", {"query": cart_request["product_query"], "limit": 5, "session_id": session_id}
    if any(token in text for token in ["tienes ", "tienen ", "tiene ", "tenes ", "hay ", "stock", "disponible", "precio", "cuesta"]):
        logger.info(
            "forced_commerce_tool_match kind=product_lookup session_id=%s message=%s",
            session_id,
            message,
        )
        return "get_product_availability", {"query": message, "limit": 5, "session_id": session_id}
    if any(token in text for token in ["despacho", "envio", "envío", "retiro", "chilexpress", "comuna"]):
        logger.info(
            "forced_commerce_tool_match kind=shipping_options session_id=%s message=%s",
            session_id,
            message,
        )
        return "get_shipping_options", {"commune": message, "session_id": session_id}
    if any(token in text for token in ["pago", "pagar", "transferencia", "mercado pago", "tarjeta"]):
        logger.info(
            "forced_commerce_tool_match kind=payment_options session_id=%s message=%s",
            session_id,
            message,
        )
        return "get_payment_options", {"session_id": session_id}
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
        return None

    clean_filename = _normalize_media_filename(filename, mime_type)
    clean_mime = (mime_type or "application/octet-stream").strip() or "application/octet-stream"
    fields: dict[str, str] = {
        "model": "whisper-1",
        "response_format": "verbose_json",
    }
    if language_hint and language_hint.strip():
        fields["language"] = language_hint.strip()

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
        raise HTTPException(status_code=503, detail=f"No se pudo transcribir audio: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail=f"No se pudo conectar al servicio de transcripcion: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="Respuesta de transcripcion invalida") from exc

    text = str(payload.get("text") or "").strip()
    if not text:
        return None

    duration_seconds = payload.get("duration")
    duration_ms = None
    if isinstance(duration_seconds, (int, float)):
        duration_ms = int(float(duration_seconds) * 1000)

    return MediaTranscriptionPayload(
        text=text,
        language=str(payload.get("language") or "").strip() or None,
        confidence=None,
        duration_ms=duration_ms,
        provider="openai",
    )


def _download_whatsapp_media_bytes(
    client: MetaWhatsAppClient | None,
    phone_number_id: str,
    media_id: str,
) -> tuple[bytes, str | None, str | None] | None:
    access_token = client.access_token if client is not None else os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    if not access_token:
        return None

    api_version = client.api_version if client is not None else os.getenv("WHATSAPP_API_VERSION", "v21.0")
    timeout_seconds = client.timeout_seconds if client is not None else int(os.getenv("WHATSAPP_API_TIMEOUT", "30"))

    media_meta_url = f"https://graph.facebook.com/{api_version}/{media_id}"
    meta_req = urllib.request.Request(
        media_meta_url,
        method="GET",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        with urllib.request.urlopen(meta_req, timeout=timeout_seconds) as response:
            meta = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    media_url = str(meta.get("url") or "").strip()
    if not media_url:
        return None

    media_req = urllib.request.Request(
        media_url,
        method="GET",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        with urllib.request.urlopen(media_req, timeout=timeout_seconds) as response:
            content = response.read()
            mime_type = str(meta.get("mime_type") or response.headers.get("content-type") or "").strip() or None
    except Exception:
        return None

    filename = _normalize_media_filename(media_id, mime_type)
    return content, mime_type, filename


def _format_canonical_tool_answer(result: dict[str, Any]) -> str | None:
    if not result.get("ok"):
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    tool = str(result.get("tool") or "")
    if tool == "get_product_availability":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        if not items:
            return "No encontré productos con ese criterio."
        first = items[0] if isinstance(items[0], dict) else {}
        name = str(first.get("name") or "Producto").strip()
        price = str(first.get("price") or "N/D").strip()
        units = str(first.get("available_units") or "0").strip()
        return f"Sí, {name} está disponible. Precio: {price}. Stock: {units}."
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
    return None


def _extract_widget_add_to_cart(message: str) -> dict[str, Any] | None:
    text = (message or "").strip().lower()
    if not text:
        return None
    match = re.search(
        r"(?:quiero|agrega|agregar|sumar|suma|llevo|pon|poner|mete|anade|añade)?\s*(\d{1,3})\s+(.+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    quantity = max(1, min(99, int(match.group(1) or "1")))
    product_query = re.sub(r"\bal\s+carrito\b", " ", match.group(2) or "", flags=re.IGNORECASE)
    product_query = re.sub(r"\?+", " ", product_query).strip()
    if not product_query:
        return None
    return {"quantity": quantity, "product_query": product_query}


def _format_public_widget_tool_payload(
    result: dict[str, Any],
    *,
    user_message: str,
    intent_label: str | None,
    channel: str | None = None,
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
            product_id = str(item.get("id") or "").strip()
            variant_id = str(item.get("id") or "").strip()
            checkout_product_id = str(item.get("code") or item.get("id") or "").strip()
            products.append(
                {
                    "id": product_id,
                    "checkout_product_id": checkout_product_id,
                    "variant_id": variant_id,
                    "name": str(item.get("name") or "Producto").strip(),
                    "price": str(item.get("price") or "N/D").strip(),
                    "stock": str(item.get("available_units") or "0").strip(),
                    "image_url": str(item.get("image_url") or "").strip() or None,
                }
            )

        cart_request = _extract_widget_add_to_cart(user_message)
        if cart_request and intent in {"product_lookup", "catalog_query", "availability_check", ""}:
            first = products[0] if products else None
            if first and first.get("id"):
                return {
                    "answer": f"Listo, agregue {cart_request['quantity']} {first['name']} al carrito. Si queres, seguimos con checkout cuando me digas \"quiero pagar\".",
                    "products": products,
                    "cart_action": {
                        "type": "add_to_cart",
                        "item": {
                            "product_id": first["checkout_product_id"] or first["id"],
                            "checkout_product_id": first["checkout_product_id"] or first["id"],
                            "variant_id": first["variant_id"] or first["id"],
                            "quantity": cart_request["quantity"],
                            "name": first["name"],
                        },
                    },
                }

        availability_tokens = ["tienen ", "tenes ", "hay ", "stock", "disponible", "precio", "cuesta"]
        normalized_message = (user_message or "").strip().lower()
        if any(token in normalized_message for token in availability_tokens):
            first = products[0]
            return {
                "answer": f"Si, {first['name']} esta disponible ahora. Precio: {first['price']}. Stock: {first['stock']}.",
                "products": products[:1],
            }

        return {"answer": "Te paso estas opciones disponibles:", "products": products}

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

    tool_answer = _format_canonical_tool_answer(result)
    if not tool_answer:
        return None
    return {"answer": tool_answer}


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
    openai_model: str = Field(default="gpt-4o-mini", min_length=3)


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
    cart_action: dict[str, Any] | None = None
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


class WhatsAppWebhookResponse(BaseModel):
    processed_messages: int
    skipped_duplicates: int
    responses: list[ChatResponsePayload]


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


def _parse_company_map(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("WHATSAPP_COMPANY_MAP debe ser un JSON valido") from exc

    if not isinstance(payload, dict):
        raise ValueError("WHATSAPP_COMPANY_MAP debe ser un objeto JSON")

    mapping: dict[str, str] = {}
    for key, value in payload.items():
        mapping[str(key)] = str(value)
    return mapping


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
    explicit = os.getenv("WHATSAPP_WEBHOOK_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    api_base_url = _public_widget_api_base_url(request)
    return f"{api_base_url}/webhooks/whatsapp"


def _whatsapp_webhook_url_internal(x_public_base_url: str | None) -> str:
    explicit = os.getenv("WHATSAPP_WEBHOOK_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    api_base_url = _public_widget_api_base_url_internal(x_public_base_url)
    return f"{api_base_url}/webhooks/whatsapp"


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


def _build_whatsapp_client() -> MetaWhatsAppClient | None:
    send_replies = os.getenv("WHATSAPP_SEND_REPLIES", "false").lower() == "true"
    if not send_replies:
        return None

    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    if not token:
        raise ValueError("WHATSAPP_SEND_REPLIES=true requiere WHATSAPP_ACCESS_TOKEN")

    return MetaWhatsAppClient(
        access_token=token,
        api_version=os.getenv("WHATSAPP_API_VERSION", "v21.0"),
        timeout_seconds=int(os.getenv("WHATSAPP_API_TIMEOUT", "30")),
        max_retries=int(os.getenv("WHATSAPP_API_MAX_RETRIES", "2")),
        backoff_seconds=float(os.getenv("WHATSAPP_API_BACKOFF_SECONDS", "0.75")),
    )


def _build_idempotency_store() -> InMemoryIdempotencyStore | RedisIdempotencyStore:
    backend = os.getenv("WHATSAPP_IDEMPOTENCY_BACKEND", "redis").strip().lower()
    ttl_seconds = int(os.getenv("WHATSAPP_IDEMPOTENCY_TTL", "300"))

    if backend == "memory":
        return InMemoryIdempotencyStore(ttl_seconds=ttl_seconds)

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return RedisIdempotencyStore(
        redis_url=redis_url,
        key_prefix=os.getenv("WHATSAPP_IDEMPOTENCY_PREFIX", "wa_dedup"),
        ttl_seconds=ttl_seconds,
    )


def _delivery_mode() -> str:
    mode = os.getenv("WHATSAPP_DELIVERY_MODE", "sync").strip().lower()
    if mode not in {"sync", "async"}:
        return "sync"
    return mode


def _truncate_for_whatsapp(text: str) -> str:
    max_chars = int(os.getenv("WHATSAPP_REPLY_MAX_CHARS", "1400"))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _idempotency_key(
    company_id: str,
    session_id: str,
    message_id: str,
    fallback_text: str,
) -> str:
    if message_id:
        return f"{company_id}:{session_id}:{message_id}"
    return f"{company_id}:{session_id}:{fallback_text[:120]}"


def _deliver_whatsapp_sync(
    client: MetaWhatsAppClient,
    phone_number_id: str,
    to_number: str,
    text: str,
) -> str:
    outbound_text = _truncate_for_whatsapp(text)
    return client.send_text_message(
        phone_number_id=phone_number_id,
        to_number=to_number,
        text=outbound_text,
    )


def _deliver_whatsapp_background(
    client: MetaWhatsAppClient,
    phone_number_id: str,
    to_number: str,
    text: str,
) -> None:
    try:
        _deliver_whatsapp_sync(
            client=client,
            phone_number_id=phone_number_id,
            to_number=to_number,
            text=text,
        )
    except Exception as exc:
        logger.exception("Fallo envio async a Meta WhatsApp: %s", exc)


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
    whatsapp_client = _build_whatsapp_client()
except Exception as exc:
    whatsapp_client = None
    startup_error = f"{startup_error}; {exc}".strip("; ")

try:
    whatsapp_company_map = _parse_company_map(os.getenv("WHATSAPP_COMPANY_MAP", ""))
except Exception as exc:
    whatsapp_company_map = {}
    startup_error = f"{startup_error}; {exc}".strip("; ")

try:
    whatsapp_idempotency_store = _build_idempotency_store()
except Exception as exc:
    whatsapp_idempotency_store = InMemoryIdempotencyStore(
        ttl_seconds=int(os.getenv("WHATSAPP_IDEMPOTENCY_TTL", "300"))
    )
    startup_error = f"{startup_error}; idempotencia en memoria: {exc}".strip("; ")

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
            openai_model=payload.openai_model,
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
            openai_model=payload.openai_model,
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
        expected_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
        configured_verify_token = (whatsapp_config.get("verify_token") or "").strip()
        has_phone_number = bool((whatsapp_config.get("phone_number_id") or "").strip())
        has_verify_token = bool(
            expected_verify_token
            and configured_verify_token
            and hmac.compare_digest(configured_verify_token, expected_verify_token)
        )
        whatsapp_ready = has_phone_number and has_verify_token
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
        expected_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
        configured_verify_token = (whatsapp_config.get("verify_token") or "").strip()
        has_phone_number = bool((whatsapp_config.get("phone_number_id") or "").strip())
        has_verify_token = bool(
            expected_verify_token
            and configured_verify_token
            and hmac.compare_digest(configured_verify_token, expected_verify_token)
        )
        whatsapp_ready = has_phone_number and has_verify_token
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
                )
                tool_answer = str((tool_payload or {}).get("answer") or "").strip()
                if tool_answer:
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
        tuned_answer = tune_answer_style(rag_result.answer, query=payload.message)

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
        raise HTTPException(status_code=503, detail="Servicio de transcripcion no disponible")
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
                )
                tool_answer = str((tool_payload or {}).get("answer") or "").strip()
                if tool_answer:
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
        tuned_answer = tune_answer_style(rag_result.answer, query=payload.message)
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

    phone_number_id = config.get("phone_number_id")
    if phone_number_id:
        whatsapp_company_map[phone_number_id] = company_id

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
    expected_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
    server_access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()

    has_phone_number_id = bool(phone_number_id)
    has_verify_token = bool(
        verify_token
        and expected_verify_token
        and hmac.compare_digest(verify_token, expected_verify_token)
    )
    server_has_access_token = bool(server_access_token)
    company_map_ready = bool(
        phone_number_id and whatsapp_company_map.get(phone_number_id) == agent.company_id
    )

    messages: list[str] = []
    if not has_phone_number_id:
        messages.append("Falta phone_number_id de Meta.")
    if not expected_verify_token:
        messages.append("El servidor no tiene WHATSAPP_VERIFY_TOKEN configurado.")
    elif not has_verify_token:
        messages.append("El verify token guardado no coincide con WHATSAPP_VERIFY_TOKEN del servidor.")
    if not server_has_access_token:
        messages.append("El servidor no tiene WHATSAPP_ACCESS_TOKEN configurado.")
    if has_phone_number_id and not company_map_ready:
        messages.append("El phone_number_id aun no esta mapeado al company_id del agente.")
    if not messages:
        messages.append("Configuracion lista para probar webhook y envios.")

    ready = has_phone_number_id and has_verify_token and server_has_access_token and company_map_ready

    return AgentWhatsAppValidationPayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        ready=ready,
        has_phone_number_id=has_phone_number_id,
        has_verify_token=has_verify_token,
        server_has_access_token=server_has_access_token,
        company_map_ready=company_map_ready,
        webhook_url=_whatsapp_webhook_url_internal(x_public_base_url),
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

    phone_number_id = config.get("phone_number_id")
    if phone_number_id:
        whatsapp_company_map[phone_number_id] = agent.company_id

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
    expected_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
    server_access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()

    has_phone_number_id = bool(phone_number_id)
    has_verify_token = bool(verify_token and expected_verify_token and hmac.compare_digest(verify_token, expected_verify_token))
    server_has_access_token = bool(server_access_token)
    company_map_ready = bool(phone_number_id and whatsapp_company_map.get(phone_number_id) == agent.company_id)

    messages: list[str] = []
    if not has_phone_number_id:
        messages.append("Falta phone_number_id de Meta.")
    if not expected_verify_token:
        messages.append("El servidor no tiene WHATSAPP_VERIFY_TOKEN configurado.")
    elif not has_verify_token:
        messages.append("El verify token guardado no coincide con WHATSAPP_VERIFY_TOKEN del servidor.")
    if not server_has_access_token:
        messages.append("El servidor no tiene WHATSAPP_ACCESS_TOKEN configurado.")
    if has_phone_number_id and not company_map_ready:
        messages.append("El phone_number_id aun no esta mapeado al company_id del agente.")
    if not messages:
        messages.append("Configuracion lista para probar webhook y envios.")

    ready = has_phone_number_id and has_verify_token and server_has_access_token and company_map_ready

    return AgentWhatsAppValidationPayload(
        agent_id=agent.agent_id,
        company_id=agent.company_id,
        ready=ready,
        has_phone_number_id=has_phone_number_id,
        has_verify_token=has_verify_token,
        server_has_access_token=server_has_access_token,
        company_map_ready=company_map_ready,
        webhook_url=_whatsapp_webhook_url(request),
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
    started = time.perf_counter()

    try:
        clubhx_tools_client = _get_clubhx_tools_client()
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
            )
            if tool_payload and tool_payload.get("answer"):
                final_answer = str(tool_payload.get("answer") or "").strip()
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
                    cart_action=tool_payload.get("cart_action") if isinstance(tool_payload.get("cart_action"), dict) else None,
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
        final_answer = rag_result.answer
    else:
        final_answer = tune_answer_style(rag_result.answer, query=payload.message)
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
        answer=tune_answer_style(result.answer, query=payload.message),
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


@app.get("/webhooks/whatsapp")
def whatsapp_verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> str:
    expected = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    if hub_mode == "subscribe" and expected and hub_verify_token == expected:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Verificacion invalida")


@app.post("/webhooks/whatsapp", response_model=WhatsAppWebhookResponse)
def whatsapp_webhook(
    payload: dict[str, object],
    background_tasks: BackgroundTasks,
) -> WhatsAppWebhookResponse:
    if chat_service is None:
        raise HTTPException(status_code=503, detail=f"Servicio no disponible: {startup_error}")

    incoming_messages = parse_whatsapp_messages(payload, company_map=whatsapp_company_map)
    responses: list[ChatResponsePayload] = []
    skipped_duplicates = 0
    delivery_mode = _delivery_mode()

    for incoming in incoming_messages:
        dedup_key = _idempotency_key(
            company_id=incoming.company_id,
            session_id=incoming.session_id,
            message_id=incoming.message_id,
            fallback_text=incoming.text,
        )
        if not whatsapp_idempotency_store.mark_if_new(dedup_key):
            skipped_duplicates += 1
            continue

        message_text = incoming.text.strip()
        if not message_text and incoming.media_id:
            media_payload = _download_whatsapp_media_bytes(
                whatsapp_client,
                incoming.phone_number_id,
                incoming.media_id,
            )
            if media_payload is not None:
                audio_bytes, mime_type, filename = media_payload
                transcription = _transcribe_audio_bytes(
                    audio_bytes=audio_bytes,
                    filename=filename or incoming.media_id,
                    mime_type=mime_type or incoming.mime_type,
                    language_hint="es",
                )
                message_text = (transcription.text if transcription else "").strip()

            if not message_text and whatsapp_client is not None:
                try:
                    _deliver_whatsapp_sync(
                        client=whatsapp_client,
                        phone_number_id=incoming.phone_number_id,
                        to_number=incoming.from_number,
                        text="Recibi tu audio, pero no pude transcribirlo. Si quieres, reenvialo o escribemelo por texto.",
                    )
                except Exception:
                    logger.exception(
                        "whatsapp_audio_transcription_failed company_id=%s message_id=%s",
                        incoming.company_id,
                        incoming.message_id,
                    )
                continue

        if not message_text:
            continue

        request = ChatRequest(
            company_id=incoming.company_id,
            session_id=incoming.session_id,
            message=message_text,
            top_k=4,
        )
        result = chat_service.chat(request)
        tuned_answer = tune_answer_style(result.answer, query=message_text)
        responses.append(
            ChatResponsePayload(
                trace_id=result.trace_id,
                company_id=result.company_id,
                session_id=result.session_id,
                answer=tuned_answer,
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
        )

        if whatsapp_client is None:
            responses[-1].delivery_status = "skipped"
            responses[-1].delivery_error = "WHATSAPP_SEND_REPLIES=false"
            continue

        try:
            if delivery_mode == "async":
                background_tasks.add_task(
                    _deliver_whatsapp_background,
                    whatsapp_client,
                    incoming.phone_number_id,
                    incoming.from_number,
                    tuned_answer,
                )
                responses[-1].delivery_status = "queued"
            else:
                message_id = _deliver_whatsapp_sync(
                    client=whatsapp_client,
                    phone_number_id=incoming.phone_number_id,
                    to_number=incoming.from_number,
                    text=tuned_answer,
                )
                responses[-1].delivery_status = "sent"
                responses[-1].delivery_message_id = message_id
        except Exception as exc:
            responses[-1].delivery_status = "failed"
            responses[-1].delivery_error = str(exc)

    return WhatsAppWebhookResponse(
        processed_messages=len(incoming_messages),
        skipped_duplicates=skipped_duplicates,
        responses=responses,
    )
