from __future__ import annotations

import json

from clasificacion_langchain.chat.session_store import SessionSummary, SessionTurn, StoredSessionSummary


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

    def _summary_index_key(self) -> str:
        return f"{self.key_prefix}:summary:index"

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
            updated_at=str(payload.get("updated_at", "")),
            workflow_reset_started_at=str(payload.get("workflow_reset_started_at", "")),
            workflow_timeout_sent_at=str(payload.get("workflow_timeout_sent_at", "")),
            user_goal=str(payload.get("user_goal", "")),
            funnel_stage=str(payload.get("funnel_stage", "")),
            checkout_stage=str(payload.get("checkout_stage", "")),
            pending_next_step=str(payload.get("pending_next_step", "")),
            awaiting_slot=str(payload.get("awaiting_slot", "")),
            last_product_query=str(payload.get("last_product_query", "")),
            selected_products=str(payload.get("selected_products", "")),
            focused_product=str(payload.get("focused_product", "")),
            cart_snapshot=str(payload.get("cart_snapshot", "")),
            shipping_preference=str(payload.get("shipping_preference", "")),
            pickup_location_label=str(payload.get("pickup_location_label", "")),
            delivery_address=str(payload.get("delivery_address", "")),
            delivery_address_confirmed=bool(payload.get("delivery_address_confirmed", False)),
            invoice_type=str(payload.get("invoice_type", "")),
            invoice_rut=str(payload.get("invoice_rut", "")),
            invoice_business_name=str(payload.get("invoice_business_name", "")),
            invoice_address=str(payload.get("invoice_address", "")),
            payment_preference=str(payload.get("payment_preference", "")),
            customer_authenticated=bool(payload.get("customer_authenticated", False)),
            order_reference=str(payload.get("order_reference", "")),
            otp_email=str(payload.get("otp_email", "")),
            authenticated_at=str(payload.get("authenticated_at", "")),
            last_tool=str(payload.get("last_tool", "")),
            last_action=str(payload.get("last_action", "")),
            notes=str(payload.get("notes", "")),
            last_channel=str(payload.get("last_channel", "")),
            reminder_recipient=str(payload.get("reminder_recipient", "")),
        )

    def save_summary(self, company_id: str, session_id: str, summary: SessionSummary) -> None:
        key = self._summary_key(company_id, session_id)
        payload = json.dumps(summary.__dict__, ensure_ascii=False)
        index_payload = json.dumps(
            {"company_id": company_id.strip(), "session_id": session_id.strip()},
            ensure_ascii=True,
            sort_keys=True,
        )
        self.client.sadd(self._summary_index_key(), index_payload)
        if self.ttl_seconds > 0:
            self.client.setex(key, self.ttl_seconds, payload)
            return
        self.client.set(key, payload)

    def list_summaries(self) -> list[StoredSessionSummary]:
        rows: list[StoredSessionSummary] = []
        stale_entries: list[str] = []
        for raw_entry in self.client.smembers(self._summary_index_key()):
            try:
                entry = json.loads(raw_entry)
            except json.JSONDecodeError:
                stale_entries.append(raw_entry)
                continue
            if not isinstance(entry, dict):
                stale_entries.append(raw_entry)
                continue

            company_id = str(entry.get("company_id", "")).strip()
            session_id = str(entry.get("session_id", "")).strip()
            if not company_id or not session_id:
                stale_entries.append(raw_entry)
                continue

            raw_summary = self.client.get(self._summary_key(company_id, session_id))
            if not raw_summary:
                stale_entries.append(raw_entry)
                continue

            rows.append(
                StoredSessionSummary(
                    company_id=company_id,
                    session_id=session_id,
                    summary=self.get_summary(company_id, session_id),
                )
            )

        if stale_entries:
            self.client.srem(self._summary_index_key(), *stale_entries)
        return rows
