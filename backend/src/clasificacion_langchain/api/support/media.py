from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from uuid import uuid4

from fastapi import HTTPException

from clasificacion_langchain.api.schemas import MediaTranscriptionPayload


logger = logging.getLogger(__name__)


def effective_chat_channel(channel: str | None, default: str) -> str:
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


def _build_multipart_body(
    fields: dict[str, str],
    file_field: tuple[str, str, bytes, str],
) -> tuple[bytes, str]:
    boundary = f"----clasificacion-{uuid4().hex}"
    chunks: list[bytes] = []

    def add_text_field(name: str, value: str) -> None:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
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


def transcribe_audio_bytes(
    *,
    audio_bytes: bytes,
    filename: str,
    mime_type: str | None,
    language_hint: str | None,
) -> MediaTranscriptionPayload:
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

    body, boundary = _build_multipart_body(
        fields,
        ("file", clean_filename, audio_bytes, clean_mime),
    )
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
        raise HTTPException(
            status_code=503,
            detail=f"No se pudo conectar al servicio de transcripcion: {exc.reason}",
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="Respuesta de transcripcion invalida") from exc

    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=503, detail="openai_empty_text")

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
