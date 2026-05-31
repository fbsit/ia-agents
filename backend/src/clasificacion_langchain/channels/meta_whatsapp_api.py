from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib import error, request


@dataclass
class MetaWhatsAppClient:
    access_token: str
    api_version: str = "v21.0"
    timeout_seconds: int = 30
    max_retries: int = 2
    backoff_seconds: float = 0.75

    def _should_retry_http(self, status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    def _sleep_for_attempt(self, attempt: int) -> None:
        delay = self.backoff_seconds * (2 ** (attempt - 1))
        time.sleep(max(delay, 0.0))

    def send_text_message(self, phone_number_id: str, to_number: str, text: str) -> str:
        if not self.access_token:
            raise ValueError("Falta WHATSAPP_ACCESS_TOKEN para enviar respuestas")

        endpoint = (
            f"https://graph.facebook.com/{self.api_version}/{phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text,
            },
        }

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
        )

        total_attempts = max(self.max_retries + 1, 1)
        last_error: Exception | None = None

        for attempt in range(1, total_attempts + 1):
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as response:
                    result = json.loads(response.read().decode("utf-8"))
                break
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                if attempt < total_attempts and self._should_retry_http(exc.code):
                    self._sleep_for_attempt(attempt)
                    continue
                raise RuntimeError(f"Meta WhatsApp devolvio HTTP error: {detail}") from exc
            except error.URLError as exc:
                last_error = exc
                if attempt < total_attempts:
                    self._sleep_for_attempt(attempt)
                    continue
                raise RuntimeError(
                    f"No se pudo conectar a Meta WhatsApp: {exc.reason}"
                ) from exc
        else:
            if last_error is not None:
                raise RuntimeError(
                    f"No se pudo conectar a Meta WhatsApp: {last_error}"
                ) from last_error
            raise RuntimeError("No se pudo completar el envio a Meta WhatsApp")

        messages = result.get("messages", [])
        if not messages:
            raise RuntimeError("Meta WhatsApp no devolvio ID de mensaje")

        first = messages[0]
        if not isinstance(first, dict):
            raise RuntimeError("Respuesta inesperada de Meta WhatsApp")

        return str(first.get("id", ""))
