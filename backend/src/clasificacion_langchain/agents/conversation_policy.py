from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


_MULTI_SPACE_PATTERN = re.compile(r"\s+")
_NON_ALNUM_PATTERN = re.compile(r"[^\w\s]", re.UNICODE)
_CLOSE_INTENT_PATTERN = re.compile(
    r"\b(gracias|muchas\s+gracias|listo|eso\s+era|era\s+todo|chau|adios|nos\s+vemos|bye)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConversationKey:
    company_id: str
    agent_id: str
    session_id: str


@dataclass
class ConversationState:
    status: str = "open"
    last_user_fingerprint: str = ""
    repeat_count: int = 0
    last_answer: str = ""
    visitor_id: str = ""
    external_user_id: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class ConversationPolicyDecision:
    action: str
    reason: str
    repeat_count: int
    answer: str | None = None


@dataclass
class _MemoryEntry:
    state: ConversationState
    expires_at: datetime | None


class InMemoryConversationStateStore:
    def __init__(self) -> None:
        self._states: dict[tuple[str, str, str], _MemoryEntry] = {}

    def _key(self, key: ConversationKey) -> tuple[str, str, str]:
        return (
            key.company_id.strip(),
            key.agent_id.strip(),
            key.session_id.strip(),
        )

    def get_state(self, key: ConversationKey) -> ConversationState:
        storage_key = self._key(key)
        entry = self._states.get(storage_key)
        now = datetime.now(UTC)
        if entry is None:
            return ConversationState(updated_at=now.isoformat())
        if entry.expires_at is not None and entry.expires_at < now:
            self._states.pop(storage_key, None)
            return ConversationState(updated_at=now.isoformat())
        return entry.state

    def save_state(self, key: ConversationKey, state: ConversationState, ttl_seconds: int) -> None:
        expires_at = None
        if ttl_seconds > 0:
            expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        self._states[self._key(key)] = _MemoryEntry(state=state, expires_at=expires_at)


class RedisConversationStateStore:
    def __init__(self, redis_url: str, key_prefix: str = "agent_conv") -> None:
        try:
            import redis
        except ImportError as exc:
            raise ImportError(
                "redis no esta instalado. Corre pip install -r requirements.txt"
            ) from exc

        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.key_prefix = key_prefix

    def _key(self, key: ConversationKey) -> str:
        return (
            f"{self.key_prefix}:{key.company_id.strip()}:{key.agent_id.strip()}:{key.session_id.strip()}"
        )

    def get_state(self, key: ConversationKey) -> ConversationState:
        row = self.client.hgetall(self._key(key))
        if not row:
            return ConversationState(updated_at=datetime.now(UTC).isoformat())

        try:
            repeat_count = int(row.get("repeat_count", "0"))
        except ValueError:
            repeat_count = 0

        return ConversationState(
            status=row.get("status", "open"),
            last_user_fingerprint=row.get("last_user_fingerprint", ""),
            repeat_count=max(0, repeat_count),
            last_answer=row.get("last_answer", ""),
            visitor_id=row.get("visitor_id", ""),
            external_user_id=row.get("external_user_id", ""),
            updated_at=row.get("updated_at", datetime.now(UTC).isoformat()),
        )

    def save_state(self, key: ConversationKey, state: ConversationState, ttl_seconds: int) -> None:
        redis_key = self._key(key)
        payload = {
            "status": state.status,
            "last_user_fingerprint": state.last_user_fingerprint,
            "repeat_count": str(state.repeat_count),
            "last_answer": state.last_answer,
            "visitor_id": state.visitor_id,
            "external_user_id": state.external_user_id,
            "updated_at": state.updated_at,
        }
        pipeline = self.client.pipeline()
        pipeline.hset(redis_key, mapping=payload)
        if ttl_seconds > 0:
            pipeline.expire(redis_key, ttl_seconds)
        pipeline.execute()


class ConversationPolicyEngine:
    def __init__(
        self,
        state_store: InMemoryConversationStateStore | RedisConversationStateStore,
        ttl_seconds: int = 86400,
        generic_repeat_threshold: int = 3,
        cached_repeat_threshold: int = 4,
    ) -> None:
        self.state_store = state_store
        self.ttl_seconds = max(60, ttl_seconds)
        self.generic_repeat_threshold = max(2, generic_repeat_threshold)
        self.cached_repeat_threshold = max(
            self.generic_repeat_threshold + 1,
            cached_repeat_threshold,
        )

    @staticmethod
    def _normalize_message(text: str) -> str:
        lowered = (text or "").strip().lower()
        if not lowered:
            return ""
        no_symbols = _NON_ALNUM_PATTERN.sub(" ", lowered)
        return _MULTI_SPACE_PATTERN.sub(" ", no_symbols).strip()

    @staticmethod
    def _fingerprint(text: str) -> str:
        if not text:
            return ""
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_close_intent(normalized_message: str) -> bool:
        if not normalized_message:
            return False
        if len(normalized_message) > 60:
            return False
        return bool(_CLOSE_INTENT_PATTERN.search(normalized_message))

    def evaluate(
        self,
        key: ConversationKey,
        message: str,
        visitor_id: str | None = None,
        external_user_id: str | None = None,
    ) -> ConversationPolicyDecision:
        state = self.state_store.get_state(key)
        normalized = self._normalize_message(message)
        fingerprint = self._fingerprint(normalized)

        if fingerprint and state.last_user_fingerprint == fingerprint:
            repeat_count = state.repeat_count + 1
        else:
            repeat_count = 1

        state.repeat_count = repeat_count
        state.last_user_fingerprint = fingerprint
        state.updated_at = datetime.now(UTC).isoformat()

        if visitor_id:
            state.visitor_id = visitor_id.strip()
        if external_user_id:
            state.external_user_id = external_user_id.strip()

        if self._is_close_intent(normalized):
            answer = (
                "Perfecto, cerramos por ahora. Si necesitas algo mas, escribime cuando quieras."
            )
            state.status = "closed"
            state.last_answer = answer
            self.state_store.save_state(key, state, self.ttl_seconds)
            return ConversationPolicyDecision(
                action="conversation_closed",
                reason="close_intent_detected",
                repeat_count=repeat_count,
                answer=answer,
            )

        if state.status == "closed":
            state.status = "open"

        if repeat_count >= self.cached_repeat_threshold and state.last_answer.strip():
            self.state_store.save_state(key, state, self.ttl_seconds)
            return ConversationPolicyDecision(
                action="repeat_cached",
                reason="repeat_threshold_cached",
                repeat_count=repeat_count,
                answer=state.last_answer,
            )

        if repeat_count >= self.generic_repeat_threshold:
            answer = (
                "Veo que repetiste la misma consulta varias veces. Para no marearte, "
                "te resumo: esta consulta ya fue respondida. Si queres, la reformulamos "
                "o te derivo con soporte humano."
            )
            state.last_answer = answer
            self.state_store.save_state(key, state, self.ttl_seconds)
            return ConversationPolicyDecision(
                action="repeat_generic",
                reason="repeat_threshold_generic",
                repeat_count=repeat_count,
                answer=answer,
            )

        self.state_store.save_state(key, state, self.ttl_seconds)
        return ConversationPolicyDecision(
            action="proceed",
            reason="normal_flow",
            repeat_count=repeat_count,
            answer=None,
        )

    def register_response(
        self,
        key: ConversationKey,
        answer: str,
        visitor_id: str | None = None,
        external_user_id: str | None = None,
    ) -> None:
        state = self.state_store.get_state(key)
        if answer.strip():
            state.last_answer = answer.strip()
        if visitor_id:
            state.visitor_id = visitor_id.strip()
        if external_user_id:
            state.external_user_id = external_user_id.strip()
        state.updated_at = datetime.now(UTC).isoformat()
        self.state_store.save_state(key, state, self.ttl_seconds)


def build_conversation_policy_from_env() -> ConversationPolicyEngine | None:
    enabled = os.getenv("AGENT_CONVERSATION_POLICY_ENABLED", "true").strip().lower()
    if enabled in {"0", "false", "no"}:
        return None

    backend = os.getenv("AGENT_CONVERSATION_STATE_BACKEND", "memory").strip().lower()
    key_prefix = os.getenv("AGENT_CONVERSATION_KEY_PREFIX", "agent_conv").strip() or "agent_conv"

    ttl_seconds_raw = os.getenv("AGENT_CONVERSATION_TTL_SECONDS", "86400").strip()
    generic_threshold_raw = os.getenv("AGENT_REPEAT_GENERIC_THRESHOLD", "3").strip()
    cached_threshold_raw = os.getenv("AGENT_REPEAT_CACHED_THRESHOLD", "4").strip()

    try:
        ttl_seconds = int(ttl_seconds_raw)
    except ValueError:
        ttl_seconds = 86400

    try:
        generic_threshold = int(generic_threshold_raw)
    except ValueError:
        generic_threshold = 3

    try:
        cached_threshold = int(cached_threshold_raw)
    except ValueError:
        cached_threshold = 4

    if backend == "redis":
        redis_url = (
            os.getenv("AGENT_CONVERSATION_REDIS_URL", "").strip()
            or os.getenv("REDIS_URL", "").strip()
            or "redis://localhost:6379/0"
        )
        try:
            store = RedisConversationStateStore(redis_url=redis_url, key_prefix=key_prefix)
            return ConversationPolicyEngine(
                state_store=store,
                ttl_seconds=ttl_seconds,
                generic_repeat_threshold=generic_threshold,
                cached_repeat_threshold=cached_threshold,
            )
        except Exception:
            pass

    store = InMemoryConversationStateStore()
    return ConversationPolicyEngine(
        state_store=store,
        ttl_seconds=ttl_seconds,
        generic_repeat_threshold=generic_threshold,
        cached_repeat_threshold=cached_threshold,
    )
