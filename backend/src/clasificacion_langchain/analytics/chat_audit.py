from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatAuditRecord:
    company_id: str
    agent_id: str
    session_id: str
    channel: str
    user_message: str
    assistant_message: str
    intent_label: str | None
    route: str | None
    response_mode: str | None
    sources_count: int
    used_llm: bool
    cached_response: bool
    latency_ms: int
    authenticated_user_id: str | None = None
    visitor_id: str | None = None
    external_user_id: str | None = None


@dataclass(frozen=True)
class ChatAuditSummaryRow:
    company_id: str
    agent_id: str
    assistant_messages: int
    cached_responses: int
    generic_repeat_responses: int
    closed_conversations: int


@dataclass(frozen=True)
class ChatAuditCostRow:
    company_id: str
    agent_id: str
    assistant_messages: int
    llm_messages: int
    avoided_llm_calls: int
    estimated_spent_usd: float
    estimated_saved_usd: float


class InMemoryChatAuditStore:
    def __init__(self) -> None:
        self._rows: list[tuple[datetime, ChatAuditRecord]] = []

    def record(self, record: ChatAuditRecord) -> None:
        self._rows.append((datetime.now(UTC), record))

    def summary(self, company_id: str | None = None, since_days: int = 30) -> list[ChatAuditSummaryRow]:
        cutoff = datetime.now(UTC) - timedelta(days=max(1, since_days))
        buckets: dict[tuple[str, str], dict[str, int]] = {}

        for created_at, record in self._rows:
            if created_at < cutoff:
                continue
            if company_id and record.company_id != company_id:
                continue

            key = (record.company_id, record.agent_id)
            if key not in buckets:
                buckets[key] = {
                    "assistant_messages": 0,
                    "cached_responses": 0,
                    "generic_repeat_responses": 0,
                    "closed_conversations": 0,
                }

            bucket = buckets[key]
            bucket["assistant_messages"] += 1
            if record.response_mode == "repeat_cached":
                bucket["cached_responses"] += 1
            if record.response_mode == "repeat_generic":
                bucket["generic_repeat_responses"] += 1
            if record.response_mode == "conversation_closed":
                bucket["closed_conversations"] += 1

        output: list[ChatAuditSummaryRow] = []
        for (row_company_id, row_agent_id), counters in sorted(buckets.items()):
            output.append(
                ChatAuditSummaryRow(
                    company_id=row_company_id,
                    agent_id=row_agent_id,
                    assistant_messages=counters["assistant_messages"],
                    cached_responses=counters["cached_responses"],
                    generic_repeat_responses=counters["generic_repeat_responses"],
                    closed_conversations=counters["closed_conversations"],
                )
            )
        return output

    def cost_summary(
        self,
        avg_llm_cost_usd: float,
        company_id: str | None = None,
        since_days: int = 30,
    ) -> list[ChatAuditCostRow]:
        cutoff = datetime.now(UTC) - timedelta(days=max(1, since_days))
        effective_cost = max(0.0, avg_llm_cost_usd)
        buckets: dict[tuple[str, str], dict[str, int]] = {}

        for created_at, record in self._rows:
            if created_at < cutoff:
                continue
            if company_id and record.company_id != company_id:
                continue

            key = (record.company_id, record.agent_id)
            if key not in buckets:
                buckets[key] = {
                    "assistant_messages": 0,
                    "llm_messages": 0,
                    "avoided_llm_calls": 0,
                }

            bucket = buckets[key]
            bucket["assistant_messages"] += 1

            short_circuit = record.response_mode in {
                "repeat_cached",
                "repeat_generic",
                "conversation_closed",
            }
            if short_circuit:
                bucket["avoided_llm_calls"] += 1
            elif record.used_llm:
                bucket["llm_messages"] += 1

        output: list[ChatAuditCostRow] = []
        for (row_company_id, row_agent_id), counters in sorted(buckets.items()):
            output.append(
                ChatAuditCostRow(
                    company_id=row_company_id,
                    agent_id=row_agent_id,
                    assistant_messages=counters["assistant_messages"],
                    llm_messages=counters["llm_messages"],
                    avoided_llm_calls=counters["avoided_llm_calls"],
                    estimated_spent_usd=round(counters["llm_messages"] * effective_cost, 6),
                    estimated_saved_usd=round(counters["avoided_llm_calls"] * effective_cost, 6),
                )
            )
        return output


class PostgresChatAuditStore:
    def __init__(self, dsn: str, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = schema

        try:
            import psycopg  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "psycopg no esta instalado. Instala psycopg[binary] para auditoria Postgres"
            ) from exc

        self._psycopg = psycopg
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(self.dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.schema}.chat_conversations (
                        id BIGSERIAL PRIMARY KEY,
                        company_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        visitor_id TEXT,
                        external_user_id TEXT,
                        authenticated_user_id TEXT,
                        status TEXT NOT NULL DEFAULT 'open',
                        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        ended_at TIMESTAMPTZ,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(company_id, agent_id, session_id, channel)
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.schema}.chat_messages (
                        id BIGSERIAL PRIMARY KEY,
                        conversation_id BIGINT NOT NULL REFERENCES {self.schema}.chat_conversations(id) ON DELETE CASCADE,
                        company_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        message_text TEXT NOT NULL,
                        intent_label TEXT,
                        route TEXT,
                        response_mode TEXT,
                        sources_count INTEGER NOT NULL DEFAULT 0,
                        used_llm BOOLEAN NOT NULL DEFAULT FALSE,
                        cached_response BOOLEAN NOT NULL DEFAULT FALSE,
                        latency_ms INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.schema}.chat_events (
                        id BIGSERIAL PRIMARY KEY,
                        conversation_id BIGINT REFERENCES {self.schema}.chat_conversations(id) ON DELETE SET NULL,
                        company_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_text TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )

                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_chat_conversations_company_agent_updated
                    ON {self.schema}.chat_conversations (company_id, agent_id, updated_at DESC)
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_chat_messages_company_created
                    ON {self.schema}.chat_messages (company_id, created_at DESC)
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_chat_messages_company_agent_created
                    ON {self.schema}.chat_messages (company_id, agent_id, created_at DESC)
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_chat_messages_response_mode_created
                    ON {self.schema}.chat_messages (response_mode, created_at DESC)
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_chat_events_company_created
                    ON {self.schema}.chat_events (company_id, created_at DESC)
                    """
                )

            conn.commit()

    def _upsert_conversation(self, cur, record: ChatAuditRecord) -> int:
        cur.execute(
            f"""
            INSERT INTO {self.schema}.chat_conversations (
                company_id, agent_id, session_id, channel,
                visitor_id, external_user_id, authenticated_user_id,
                status, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', NOW())
            ON CONFLICT (company_id, agent_id, session_id, channel)
            DO UPDATE SET
                visitor_id = COALESCE(EXCLUDED.visitor_id, {self.schema}.chat_conversations.visitor_id),
                external_user_id = COALESCE(EXCLUDED.external_user_id, {self.schema}.chat_conversations.external_user_id),
                authenticated_user_id = COALESCE(EXCLUDED.authenticated_user_id, {self.schema}.chat_conversations.authenticated_user_id),
                updated_at = NOW()
            RETURNING id
            """,
            (
                record.company_id,
                record.agent_id,
                record.session_id,
                record.channel,
                record.visitor_id,
                record.external_user_id,
                record.authenticated_user_id,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("No se pudo crear/actualizar la conversacion")
        return int(row[0])

    def record(self, record: ChatAuditRecord) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                conversation_id = self._upsert_conversation(cur, record)

                cur.execute(
                    f"""
                    INSERT INTO {self.schema}.chat_messages (
                        conversation_id, company_id, agent_id, session_id,
                        role, message_text, sources_count, used_llm, cached_response, latency_ms
                    ) VALUES (%s, %s, %s, %s, 'user', %s, 0, FALSE, FALSE, 0)
                    """,
                    (
                        conversation_id,
                        record.company_id,
                        record.agent_id,
                        record.session_id,
                        record.user_message,
                    ),
                )

                cur.execute(
                    f"""
                    INSERT INTO {self.schema}.chat_messages (
                        conversation_id, company_id, agent_id, session_id,
                        role, message_text, intent_label, route, response_mode,
                        sources_count, used_llm, cached_response, latency_ms
                    ) VALUES (%s, %s, %s, %s, 'assistant', %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        conversation_id,
                        record.company_id,
                        record.agent_id,
                        record.session_id,
                        record.assistant_message,
                        record.intent_label,
                        record.route,
                        record.response_mode,
                        record.sources_count,
                        record.used_llm,
                        record.cached_response,
                        record.latency_ms,
                    ),
                )

                cur.execute(
                    f"""
                    UPDATE {self.schema}.chat_conversations
                    SET
                        message_count = message_count + 2,
                        updated_at = NOW(),
                        status = CASE WHEN %s = 'conversation_closed' THEN 'closed' ELSE status END,
                        ended_at = CASE WHEN %s = 'conversation_closed' THEN NOW() ELSE ended_at END
                    WHERE id = %s
                    """,
                    (
                        record.response_mode,
                        record.response_mode,
                        conversation_id,
                    ),
                )

                if record.response_mode in {"repeat_cached", "repeat_generic", "conversation_closed"}:
                    cur.execute(
                        f"""
                        INSERT INTO {self.schema}.chat_events (
                            conversation_id, company_id, agent_id, session_id, event_type, payload_text
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            conversation_id,
                            record.company_id,
                            record.agent_id,
                            record.session_id,
                            record.response_mode,
                            f"route={record.route or ''};intent={record.intent_label or ''}",
                        ),
                    )

            conn.commit()

    def summary(self, company_id: str | None = None, since_days: int = 30) -> list[ChatAuditSummaryRow]:
        params: list[object] = [max(1, since_days)]
        where_company = ""
        if company_id:
            where_company = " AND company_id = %s"
            params.append(company_id)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        company_id,
                        agent_id,
                        COUNT(*) FILTER (WHERE role = 'assistant') AS assistant_messages,
                        COUNT(*) FILTER (WHERE role = 'assistant' AND response_mode = 'repeat_cached') AS cached_responses,
                        COUNT(*) FILTER (WHERE role = 'assistant' AND response_mode = 'repeat_generic') AS generic_repeat_responses,
                        COUNT(*) FILTER (WHERE role = 'assistant' AND response_mode = 'conversation_closed') AS closed_conversations
                    FROM {self.schema}.chat_messages
                    WHERE created_at >= NOW() - (%s::text || ' days')::interval
                    {where_company}
                    GROUP BY company_id, agent_id
                    ORDER BY company_id, agent_id
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()

        return [
            ChatAuditSummaryRow(
                company_id=str(row[0]),
                agent_id=str(row[1]),
                assistant_messages=int(row[2]),
                cached_responses=int(row[3]),
                generic_repeat_responses=int(row[4]),
                closed_conversations=int(row[5]),
            )
            for row in rows
        ]

    def cost_summary(
        self,
        avg_llm_cost_usd: float,
        company_id: str | None = None,
        since_days: int = 30,
    ) -> list[ChatAuditCostRow]:
        params: list[object] = [max(1, since_days)]
        where_company = ""
        if company_id:
            where_company = " AND company_id = %s"
            params.append(company_id)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        company_id,
                        agent_id,
                        COUNT(*) FILTER (WHERE role = 'assistant') AS assistant_messages,
                        COUNT(*) FILTER (
                            WHERE role = 'assistant' AND used_llm = TRUE
                            AND COALESCE(response_mode, '') NOT IN ('repeat_cached', 'repeat_generic', 'conversation_closed')
                        ) AS llm_messages,
                        COUNT(*) FILTER (
                            WHERE role = 'assistant'
                            AND COALESCE(response_mode, '') IN ('repeat_cached', 'repeat_generic', 'conversation_closed')
                        ) AS avoided_llm_calls
                    FROM {self.schema}.chat_messages
                    WHERE created_at >= NOW() - (%s::text || ' days')::interval
                    {where_company}
                    GROUP BY company_id, agent_id
                    ORDER BY company_id, agent_id
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()

        effective_cost = max(0.0, avg_llm_cost_usd)
        return [
            ChatAuditCostRow(
                company_id=str(row[0]),
                agent_id=str(row[1]),
                assistant_messages=int(row[2]),
                llm_messages=int(row[3]),
                avoided_llm_calls=int(row[4]),
                estimated_spent_usd=round(int(row[3]) * effective_cost, 6),
                estimated_saved_usd=round(int(row[4]) * effective_cost, 6),
            )
            for row in rows
        ]


class ChatAuditService:
    def __init__(
        self,
        store: InMemoryChatAuditStore | PostgresChatAuditStore | None,
    ) -> None:
        self.store = store

    def enabled(self) -> bool:
        return self.store is not None

    def record(self, record: ChatAuditRecord) -> None:
        if self.store is None:
            return
        self.store.record(record)

    def summary(self, company_id: str | None = None, since_days: int = 30) -> list[ChatAuditSummaryRow]:
        if self.store is None:
            return []
        return self.store.summary(company_id=company_id, since_days=since_days)

    def cost_summary(
        self,
        avg_llm_cost_usd: float,
        company_id: str | None = None,
        since_days: int = 30,
    ) -> list[ChatAuditCostRow]:
        if self.store is None:
            return []
        return self.store.cost_summary(
            avg_llm_cost_usd=avg_llm_cost_usd,
            company_id=company_id,
            since_days=since_days,
        )


def build_chat_audit_service_from_env() -> ChatAuditService:
    backend = os.getenv("CHAT_AUDIT_BACKEND", "none").strip().lower()

    if backend in {"", "none", "off", "disabled"}:
        return ChatAuditService(store=None)

    if backend == "memory":
        return ChatAuditService(store=InMemoryChatAuditStore())

    if backend == "postgres":
        dsn = os.getenv("CHAT_AUDIT_POSTGRES_DSN", "").strip()
        schema = os.getenv("CHAT_AUDIT_POSTGRES_SCHEMA", "public").strip() or "public"
        if not dsn:
            logger.warning("chat_audit_disabled reason=missing_postgres_dsn")
            return ChatAuditService(store=None)
        try:
            store = PostgresChatAuditStore(dsn=dsn, schema=schema)
            return ChatAuditService(store=store)
        except Exception as exc:
            logger.warning("chat_audit_disabled reason=postgres_init_failed detail=%s", exc)
            return ChatAuditService(store=None)

    logger.warning("chat_audit_disabled reason=unknown_backend backend=%s", backend)
    return ChatAuditService(store=None)
