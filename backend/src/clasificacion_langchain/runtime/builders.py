from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from clasificacion_langchain.agents.conversation_policy import build_conversation_policy_from_env
from clasificacion_langchain.agents.postgres_repository import PostgresAgentRepository
from clasificacion_langchain.agents.repository import InMemoryAgentRepository
from clasificacion_langchain.agents.service import AgentService
from clasificacion_langchain.agents.sqlite_repository import SQLiteAgentRepository
from clasificacion_langchain.auth.service import AuthService
from clasificacion_langchain.auth.token_service import TokenService
from clasificacion_langchain.chat.config import ChatServiceConfig
from clasificacion_langchain.chat.memory_store import InMemorySessionStore
from clasificacion_langchain.chat.redis_store import RedisSessionStore
from clasificacion_langchain.chat.service import ChatService
from clasificacion_langchain.persistence.inmemory_identity_store import InMemoryIdentityStore
from clasificacion_langchain.persistence.postgres_identity_store import PostgresIdentityStore
from clasificacion_langchain.persistence.sqlite_identity_store import SQLiteIdentityStore
from clasificacion_langchain.settings.postgres_store import PostgresTenantLlmSettingsStore
from clasificacion_langchain.settings.service import InMemoryTenantLlmSettingsStore, TenantLlmSettingsService
from clasificacion_langchain.settings.sqlite_store import SQLiteTenantLlmSettingsStore
from clasificacion_langchain.tenancy.service import TenancyService


load_dotenv()

logger = logging.getLogger(__name__)


def parse_rag_intents(raw: str) -> set[str]:
    values = [item.strip() for item in raw.split(",")]
    return {value for value in values if value}


def chat_auth_compat_mode() -> bool:
    return os.getenv("CHAT_AUTH_COMPAT_MODE", "true").strip().lower() == "true"


def persistence_backend() -> str:
    backend = os.getenv("PERSISTENCE_BACKEND", "").strip().lower()
    if backend in {"sqlite", "memory", "postgres"}:
        return backend
    if os.getenv("POSTGRES_DSN", "").strip() or os.getenv("DATABASE_URL", "").strip():
        return "postgres"
    return "sqlite"


def postgres_dsn() -> str:
    candidate = os.getenv("POSTGRES_DSN", "").strip() or os.getenv("DATABASE_URL", "").strip()
    if candidate:
        return candidate
    raise ValueError("POSTGRES_DSN o DATABASE_URL es requerido cuando PERSISTENCE_BACKEND=postgres")


def sqlite_db_path() -> str:
    default_path = Path(__file__).resolve().parents[4] / "data" / "local_api.db"
    return os.getenv("SQLITE_DB_PATH", str(default_path))


def build_session_store_for_agents(*, max_turns: int):
    backend = os.getenv("AGENT_CHAT_SESSION_BACKEND", "auto").strip().lower()
    if backend == "auto":
        backend = "redis" if os.getenv("REDIS_URL", "").strip() else "memory"
    if backend == "redis":
        redis_url = os.getenv("REDIS_URL", "").strip()
        if redis_url:
            return RedisSessionStore(
                redis_url=redis_url,
                key_prefix=os.getenv("AGENT_CHAT_REDIS_KEY_PREFIX", "agent_chat_session"),
                max_turns=max_turns,
                ttl_seconds=int(os.getenv("AGENT_CHAT_REDIS_TTL_SECONDS", "86400")),
            )
        logger.warning("AGENT_CHAT_SESSION_BACKEND=redis pero REDIS_URL no esta definido; fallback memory")
    return InMemorySessionStore(max_turns=max_turns)


def build_service() -> ChatService:
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
        rag_intents=parse_rag_intents(os.getenv("CHAT_RAG_INTENTS", "")),
        session_backend=configured_backend,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        redis_key_prefix=os.getenv("REDIS_KEY_PREFIX", "chat_session"),
        redis_ttl_seconds=int(os.getenv("REDIS_TTL_SECONDS", "86400")),
        max_session_turns=int(os.getenv("CHAT_MAX_SESSION_TURNS", "12")),
    )
    if config.session_backend.strip().lower() == "redis":
        store = RedisSessionStore(
            redis_url=config.redis_url,
            key_prefix=config.redis_key_prefix,
            max_turns=config.max_session_turns,
            ttl_seconds=config.redis_ttl_seconds,
        )
    else:
        store = InMemorySessionStore(max_turns=config.max_session_turns)
    return ChatService(config=config, session_store=store)


def build_identity_stack() -> tuple[AuthService, TenancyService, TokenService]:
    token_service = TokenService.from_env()
    backend = persistence_backend()
    if backend == "sqlite":
        store = SQLiteIdentityStore(sqlite_db_path())
    elif backend == "postgres":
        store = PostgresIdentityStore(postgres_dsn())
    else:
        store = InMemoryIdentityStore()
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


def build_llm_settings_service() -> TenantLlmSettingsService:
    backend = persistence_backend()
    if backend == "sqlite":
        store = SQLiteTenantLlmSettingsStore(sqlite_db_path())
    elif backend == "postgres":
        store = PostgresTenantLlmSettingsStore(postgres_dsn())
    else:
        store = InMemoryTenantLlmSettingsStore()
    return TenantLlmSettingsService(
        store=store,
        default_generation_provider=os.getenv("RAG_GENERATION_PROVIDER", "auto"),
        default_openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        default_anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
    )


def build_agent_service(llm_settings_service: TenantLlmSettingsService | None) -> AgentService:
    backend = persistence_backend()
    if backend == "sqlite":
        repository = SQLiteAgentRepository(sqlite_db_path())
    elif backend == "postgres":
        repository = PostgresAgentRepository(postgres_dsn())
    else:
        repository = InMemoryAgentRepository()
    conversation_policy = build_conversation_policy_from_env()
    session_store = build_session_store_for_agents(max_turns=int(os.getenv("AGENT_CHAT_MAX_SESSION_TURNS", "12")))
    return AgentService(
        repository=repository,
        llm_settings_service=llm_settings_service,
        conversation_policy=conversation_policy,
        session_store=session_store,
        knowledge_root=os.getenv("AGENTS_KNOWLEDGE_ROOT", "knowledge_base/agents"),
        index_root=os.getenv("AGENTS_INDEX_ROOT", "models/agents"),
    )
