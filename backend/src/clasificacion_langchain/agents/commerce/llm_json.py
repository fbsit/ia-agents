from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def call_openai_json(
    *,
    messages: list[dict[str, str]],
    temperature: float,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    request_payload = {
        "model": model,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": messages,
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
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    content = str(
        (((payload.get("choices") or [None])[0] or {}).get("message") or {}).get("content") or ""
    ).strip()
    parsed = json.loads(content) if content else {}
    return parsed if isinstance(parsed, dict) else None
