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
from starlette.datastructures import Headers

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


class PublicWidgetCORSMiddleware:
    """CORS propio de `/public/widget/*`, gobernado por PUBLIC_WIDGET_ALLOW_ORIGINS.

    El `CORSMiddleware` global de la app solo permite `CORS_ALLOW_ORIGINS`
    (localhost por default) porque protege la API autenticada. El widget
    embebible lo llama un navegador de terceros (el dominio del integrador,
    desconocido de antemano) y se autentica con `widget_token`, no cookies:
    necesita su propia politica de origen, mas permisiva, sin tocar la del
    resto de la API. Responde el preflight OPTIONS directo y agrega el header
    a la respuesta real; si el origen ya trae headers CORS del middleware
    global (coincide con la whitelist de localhost) los reemplaza para no
    duplicar `Access-Control-Allow-Origin`.

    `path` es un PREFIJO (no una ruta exacta): cubre tanto `/public/widget/chat`
    como `/public/widget/chat/stream` (SSE de respuestas humanas en vivo), que
    el navegador del cliente llama cross-origin igual que al chat.
    """

    def __init__(self, app, path: str) -> None:
        self.app = app
        self.path = path

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not str(scope.get("path") or "").startswith(self.path):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if not origin:
            await self.app(scope, receive, send)
            return

        if not public_widget_origin_allowed(origin):
            allow_origin = None
        elif "*" in public_widget_allowed_origins():
            # El widget no usa cookies/credenciales, asi que "*" es valido y
            # ademas es el unico valor que los navegadores aceptan para un
            # origen "null" (paginas file:// o sandboxed): reflejar ese origen
            # literalmente no funciona en la practica.
            allow_origin = "*"
        else:
            allow_origin = origin

        if scope["method"] == "OPTIONS" and headers.get("access-control-request-method"):
            response_headers = [(b"vary", b"origin")]
            if allow_origin:
                requested_headers = headers.get("access-control-request-headers")
                response_headers.extend(
                    [
                        (b"access-control-allow-origin", allow_origin.encode("latin-1")),
                        (b"access-control-allow-methods", b"POST, OPTIONS"),
                        (b"access-control-max-age", b"600"),
                    ]
                )
                if requested_headers:
                    response_headers.append(
                        (b"access-control-allow-headers", requested_headers.encode("latin-1"))
                    )
            await send({"type": "http.response.start", "status": 204, "headers": response_headers})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message: dict) -> None:
            if message["type"] == "http.response.start" and allow_origin:
                filtered = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in (b"access-control-allow-origin", b"vary")
                ]
                filtered.append((b"access-control-allow-origin", allow_origin.encode("latin-1")))
                filtered.append((b"vary", b"origin"))
                message = {**message, "headers": filtered}
            await send(message)

        await self.app(scope, receive, send_with_cors)


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


# Debe coincidir con el `api_prefix` que api/app.py usa para montar todos los
# routers (incluido el de widget/internal). PUBLIC_WIDGET_API_BASE_URL y
# X-Public-Base-Url solo llevan el dominio publico (lo que configura el
# usuario/Spring); las rutas reales siempre viven bajo este prefijo, asi que
# hay que agregarlo aca en vez de pedirselo a quien configura el dominio.
PUBLIC_API_PREFIX = "/api"


def public_widget_api_base_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_WIDGET_API_BASE_URL", "").strip()
    base = configured.rstrip("/") if configured else str(request.base_url).rstrip("/")
    return f"{base}{PUBLIC_API_PREFIX}"


def public_widget_api_base_url_internal(x_public_base_url: str | None) -> str:
    override = (x_public_base_url or "").strip()
    if override:
        base = override.rstrip("/")
    else:
        configured = os.getenv("PUBLIC_WIDGET_API_BASE_URL", "").strip()
        base = configured.rstrip("/") if configured else "http://localhost:8080"
    return f"{base}{PUBLIC_API_PREFIX}"


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
    """
    Snippet HTML autocontenido: boton flotante + panel de chat + JS que llama a
    POST /public/widget/chat. Es lo que un integrador pega tal cual en su sitio.
    """
    payload = {"apiBaseUrl": api_base_url, "widgetId": widget_id, "widgetToken": widget_token}
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
.northline-checkout-link{display:inline-block;margin-top:6px;padding:8px 12px;border-radius:8px;background:#0f766e;color:#fff;text-decoration:none;font-size:13px;font-weight:600;}
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

  function addCheckoutLink(url){
    const link = document.createElement("a");
    link.className = "northline-checkout-link";
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Ir a pagar";
    messages.appendChild(link);
    messages.scrollTop = messages.scrollHeight;
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
      if (data && data.redirect_to) {
        addCheckoutLink(data.redirect_to);
      }
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
