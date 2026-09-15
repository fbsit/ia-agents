from __future__ import annotations

import hashlib
import hmac
import os
import time
from uuid import uuid4

from fastapi import HTTPException

from clasificacion_langchain.auth.schemas import AuthPrincipal
from clasificacion_langchain.auth.token_service import AuthTokenError
from clasificacion_langchain.api.support.presenters import extract_bearer_token


def require_principal(authorization: str | None, token_service=None) -> AuthPrincipal:
    if token_service is None:
        raise HTTPException(status_code=503, detail="Auth no disponible en este entorno")

    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Falta Bearer token")

    try:
        return token_service.validate_access_token(token)
    except AuthTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_internal_context(
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

    validate_internal_signature(
        company_id=company_id,
        org_id=org_id,
        user_id=user_id,
        request_id=request_id,
        signature=x_platform_signature,
        timestamp=x_platform_timestamp,
    )

    return company_id, org_id, user_id, request_id


def validate_internal_signature(
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

    canonical = "\n".join([clean_timestamp, company_id, org_id, user_id, request_id])
    expected = hmac.new(
        shared_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, clean_signature):
        raise HTTPException(status_code=401, detail="Firma interna invalida")
