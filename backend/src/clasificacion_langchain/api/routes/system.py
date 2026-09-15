from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "ai-engine",
        "entrypoint": "chat_api_next",
        "architecture": {
            "objective": "adaptar HTTP al runtime AI sin mezclar negocio en el entrypoint",
            "owns": ["app", "routers", "dependencies", "lifecycle"],
            "delegates_to": [
                "AuthService",
                "TenancyService",
                "ChatService",
                "AgentService",
            ],
        },
    }
