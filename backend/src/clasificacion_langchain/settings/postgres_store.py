from __future__ import annotations

from datetime import UTC, datetime

from clasificacion_langchain.settings.service import TenantLlmSettings
from clasificacion_langchain.persistence.pg_connections import pooled_connection


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PostgresTenantLlmSettingsStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        try:
            import psycopg  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "psycopg no esta instalado para PERSISTENCE_BACKEND=postgres"
            ) from exc
        self._psycopg = psycopg
        self._ensure_schema()

    def _connect(self):
        return pooled_connection(self._psycopg, self.dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tenant_llm_settings (
                        company_id TEXT PRIMARY KEY,
                        generation_provider TEXT NOT NULL,
                        openai_model TEXT NOT NULL,
                        anthropic_model TEXT NOT NULL,
                        openai_api_key TEXT NOT NULL,
                        anthropic_api_key TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            conn.commit()

    def get(self, company_id: str) -> TenantLlmSettings | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM tenant_llm_settings WHERE company_id = %s",
                    (company_id.strip().lower(),),
                )
                row = cur.fetchone()

        if row is None:
            return None

        updated_at = row[6]
        if not isinstance(updated_at, datetime):
            updated_at = _utcnow()

        return TenantLlmSettings(
            company_id=row[0],
            generation_provider=row[1],
            openai_model=row[2],
            anthropic_model=row[3],
            openai_api_key=row[4],
            anthropic_api_key=row[5],
            updated_at=updated_at,
        )

    def save(self, settings: TenantLlmSettings) -> TenantLlmSettings:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tenant_llm_settings (
                        company_id, generation_provider, openai_model, anthropic_model,
                        openai_api_key, anthropic_api_key, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(company_id) DO UPDATE SET
                        generation_provider=EXCLUDED.generation_provider,
                        openai_model=EXCLUDED.openai_model,
                        anthropic_model=EXCLUDED.anthropic_model,
                        openai_api_key=EXCLUDED.openai_api_key,
                        anthropic_api_key=EXCLUDED.anthropic_api_key,
                        updated_at=EXCLUDED.updated_at
                    """,
                    (
                        settings.company_id.strip().lower(),
                        settings.generation_provider,
                        settings.openai_model,
                        settings.anthropic_model,
                        settings.openai_api_key,
                        settings.anthropic_api_key,
                        settings.updated_at,
                    ),
                )
            conn.commit()
        return settings
