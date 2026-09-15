from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException, Request

from clasificacion_langchain.integrations.clubhx import ClubHxToolsClient


logger = logging.getLogger(__name__)

PUBLIC_WIDGET_RATE_LOCK = threading.Lock()
PUBLIC_WIDGET_RATE_EVENTS: dict[str, list[float]] = {}

_clubhx_tools_client: ClubHxToolsClient | None = None
_clubhx_tools_signature: tuple[str, str, str, int] | None = None


def configure_agent_usage_logging() -> None:
    load_dotenv()
    raw_path = os.getenv("AGENT_USAGE_LOG_PATH", "logs/agent_usage.log").strip()
    if not raw_path:
        return
    log_path = Path(raw_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return


def get_clubhx_tools_client() -> ClubHxToolsClient | None:
    global _clubhx_tools_client, _clubhx_tools_signature
    base_url = os.getenv("CLUBHX_API_BASE_URL", "").strip()
    service_token = os.getenv("CLUBHX_SERVICE_TOKEN", "").strip()
    shop_domain = os.getenv("CLUBHX_SHOP_DOMAIN", "").strip() or os.getenv("SHOP_DOMAIN", "").strip()
    timeout_seconds = int(os.getenv("CLUBHX_TOOLS_TIMEOUT_SECONDS", "12") or "12")
    if not base_url or not service_token:
        _clubhx_tools_client = None
        _clubhx_tools_signature = None
        return None
    signature = (base_url, service_token, shop_domain, timeout_seconds)
    if _clubhx_tools_client is None or _clubhx_tools_signature != signature:
        _clubhx_tools_client = ClubHxToolsClient(
            base_url=base_url,
            service_token=service_token,
            shop_domain=shop_domain or None,
            timeout_seconds=timeout_seconds,
        )
        _clubhx_tools_signature = signature
    return _clubhx_tools_client


def is_agent_whatsapp_config_ready(config: dict[str, str | None]) -> bool:
    return bool((config.get("phone_number_id") or "").strip()) and bool((config.get("verify_token") or "").strip())


def public_widget_allowed_origins() -> list[str]:
    raw = os.getenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "*").strip()
    if not raw:
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]


def public_widget_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    allowed = public_widget_allowed_origins()
    return "*" in allowed or origin in allowed


def public_widget_rate_limit_window_seconds() -> int:
    try:
        return max(1, int(os.getenv("PUBLIC_WIDGET_RATE_LIMIT_WINDOW_SECONDS", "60").strip()))
    except ValueError:
        return 60


def public_widget_rate_limit_max_requests() -> int:
    try:
        return max(1, int(os.getenv("PUBLIC_WIDGET_RATE_LIMIT_MAX_REQUESTS", "30").strip()))
    except ValueError:
        return 30


def public_widget_signing_secret() -> str:
    return os.getenv("PUBLIC_WIDGET_SIGNING_SECRET", "").strip() or os.getenv("AUTH_SECRET_KEY", "").strip()


def public_widget_token(agent_id: str, company_id: str) -> str:
    secret = public_widget_signing_secret()
    if not secret:
        raise RuntimeError("PUBLIC_WIDGET_SIGNING_SECRET no configurado (o AUTH_SECRET_KEY vacio)")
    payload = f"{agent_id}:{company_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def public_widget_api_base_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_WIDGET_API_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def public_widget_api_base_url_internal(x_public_base_url: str | None) -> str:
    override = (x_public_base_url or "").strip()
    if override:
        return override.rstrip("/")
    configured = os.getenv("PUBLIC_WIDGET_API_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    return "http://localhost:8080"


def public_widget_session_id(widget_id: str, session_id: str | None) -> str:
    clean = (session_id or "").strip()
    if clean:
        return clean
    return f"widget-{widget_id[:8]}-{os.urandom(6).hex()}"


def public_widget_client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def public_widget_rate_limit_retry_after(widget_id: str, client_id: str) -> int | None:
    window_seconds = public_widget_rate_limit_window_seconds()
    max_requests = public_widget_rate_limit_max_requests()
    key = f"{widget_id}:{client_id}"
    now = time.time()
    with PUBLIC_WIDGET_RATE_LOCK:
        previous = PUBLIC_WIDGET_RATE_EVENTS.get(key, [])
        recent = [timestamp for timestamp in previous if now - timestamp < window_seconds]
        if len(recent) >= max_requests:
            oldest = recent[0]
            PUBLIC_WIDGET_RATE_EVENTS[key] = recent
            return max(1, int(window_seconds - (now - oldest)))
        recent.append(now)
        PUBLIC_WIDGET_RATE_EVENTS[key] = recent
        return None


def public_widget_snippet(api_base_url: str, widget_id: str, widget_token: str) -> str:
    payload = {"apiBaseUrl": api_base_url, "widgetId": widget_id, "widgetToken": widget_token}
    config_json = json.dumps(payload, ensure_ascii=True)
    return (
        '<script>(function(){window.NORTHLINE_WIDGET_CONFIG=' + config_json + ';})();</script>'
    )
