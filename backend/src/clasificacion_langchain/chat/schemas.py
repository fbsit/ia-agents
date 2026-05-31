from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChatRequest:
    company_id: str
    session_id: str
    message: str
    top_k: int = 4
    generation_provider: str | None = None
    generation_model: str | None = None
    use_openai_generation: bool | None = None


@dataclass
class AuthenticatedChatContext:
    user_id: str
    company_id: str
    roles: list[str]


@dataclass
class ChatResponse:
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
