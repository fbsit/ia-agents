from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from clasificacion_langchain.settings.service import TenantLlmSettings


class SQLiteTenantLlmSettingsStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        default_path = Path(__file__).resolve().parents[4] / "data" / "local_api.db"
        self.db_path = str(db_path or default_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_llm_settings (
                    company_id TEXT PRIMARY KEY,
                    generation_provider TEXT NOT NULL,
                    openai_model TEXT NOT NULL,
                    anthropic_model TEXT NOT NULL,
                    openai_api_key TEXT NOT NULL,
                    anthropic_api_key TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get(self, company_id: str) -> TenantLlmSettings | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tenant_llm_settings WHERE company_id = ?",
                (company_id.strip().lower(),),
            ).fetchone()

        if row is None:
            return None

        return TenantLlmSettings(
            company_id=row["company_id"],
            generation_provider=row["generation_provider"],
            openai_model=row["openai_model"],
            anthropic_model=row["anthropic_model"],
            openai_api_key=row["openai_api_key"],
            anthropic_api_key=row["anthropic_api_key"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def save(self, settings: TenantLlmSettings) -> TenantLlmSettings:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenant_llm_settings (
                    company_id, generation_provider, openai_model, anthropic_model,
                    openai_api_key, anthropic_api_key, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_id) DO UPDATE SET
                    generation_provider=excluded.generation_provider,
                    openai_model=excluded.openai_model,
                    anthropic_model=excluded.anthropic_model,
                    openai_api_key=excluded.openai_api_key,
                    anthropic_api_key=excluded.anthropic_api_key,
                    updated_at=excluded.updated_at
                """,
                (
                    settings.company_id.strip().lower(),
                    settings.generation_provider,
                    settings.openai_model,
                    settings.anthropic_model,
                    settings.openai_api_key,
                    settings.anthropic_api_key,
                    settings.updated_at.isoformat(),
                ),
            )
        return settings
