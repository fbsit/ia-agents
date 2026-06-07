from __future__ import annotations

import json

from clasificacion_langchain.chat.session_store import SessionSummary, SessionTurn


class RedisSessionStore:
    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "chat_session",
        max_turns: int = 12,
        ttl_seconds: int = 86400,
    ) -> None:
        try:
            import redis
        except ImportError as exc:
            raise ImportError(
                "redis no esta instalado. Corre pip install -r requirements.txt"
            ) from exc

        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.key_prefix = key_prefix
        self.max_turns = max_turns
        self.ttl_seconds = ttl_seconds

    def _key(self, company_id: str, session_id: str) -> str:
        return f"{self.key_prefix}:{company_id.strip()}:{session_id.strip()}"

    def _summary_key(self, company_id: str, session_id: str) -> str:
        return f"{self.key_prefix}:summary:{company_id.strip()}:{session_id.strip()}"

    def _append_turn(self, company_id: str, session_id: str, role: str, text: str) -> None:
        key = self._key(company_id, session_id)
        payload = json.dumps({"role": role, "text": text}, ensure_ascii=False)

        pipeline = self.client.pipeline()
        pipeline.rpush(key, payload)
        pipeline.ltrim(key, -self.max_turns, -1)
        if self.ttl_seconds > 0:
            pipeline.expire(key, self.ttl_seconds)
        pipeline.execute()

    def append_user_message(self, company_id: str, session_id: str, text: str) -> None:
        self._append_turn(company_id, session_id, "user", text)

    def append_assistant_message(self, company_id: str, session_id: str, text: str) -> None:
        self._append_turn(company_id, session_id, "assistant", text)

    def recent_turns(
        self,
        company_id: str,
        session_id: str,
        limit: int = 4,
    ) -> list[SessionTurn]:
        if limit <= 0:
            return []

        key = self._key(company_id, session_id)
        raw_items = self.client.lrange(key, -limit, -1)
        turns: list[SessionTurn] = []

        for raw in raw_items:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue

            role = str(payload.get("role", "assistant"))
            text = str(payload.get("text", ""))
            turns.append(SessionTurn(role=role, text=text))

        return turns

    def get_summary(self, company_id: str, session_id: str) -> SessionSummary:
        raw = self.client.get(self._summary_key(company_id, session_id))
        if not raw:
            return SessionSummary()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return SessionSummary()
        if not isinstance(payload, dict):
            return SessionSummary()
        return SessionSummary(
            user_goal=str(payload.get("user_goal", "")),
            funnel_stage=str(payload.get("funnel_stage", "")),
            last_product_query=str(payload.get("last_product_query", "")),
            selected_products=str(payload.get("selected_products", "")),
            shipping_preference=str(payload.get("shipping_preference", "")),
            payment_preference=str(payload.get("payment_preference", "")),
            order_reference=str(payload.get("order_reference", "")),
            last_tool=str(payload.get("last_tool", "")),
            last_action=str(payload.get("last_action", "")),
            notes=str(payload.get("notes", "")),
        )

    def save_summary(self, company_id: str, session_id: str, summary: SessionSummary) -> None:
        key = self._summary_key(company_id, session_id)
        payload = json.dumps(summary.__dict__, ensure_ascii=False)
        if self.ttl_seconds > 0:
            self.client.setex(key, self.ttl_seconds, payload)
            return
        self.client.set(key, payload)
