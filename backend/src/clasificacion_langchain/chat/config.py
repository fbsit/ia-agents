from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChatServiceConfig:
    rag_index_path: str = "models/rag_index.joblib"
    intent_model_path: str = "models/intent_router.joblib"
    use_openai: bool = False
    openai_model: str = "gpt-4o-mini"
    generation_provider: str = "auto"
    anthropic_model: str = "claude-sonnet-4-6"
    confidence_threshold: float = 0.45
    rag_intents: set[str] = field(default_factory=set)
    session_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    redis_key_prefix: str = "chat_session"
    redis_ttl_seconds: int = 86400
    max_session_turns: int = 12
