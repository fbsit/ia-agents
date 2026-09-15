from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from clasificacion_langchain.agents.repository import AgentDocumentRecord, AgentRecord


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SQLiteAgentRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
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
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    tone TEXT NOT NULL,
                    description TEXT NOT NULL,
                    rag_backend TEXT NOT NULL,
                    generation_provider TEXT NOT NULL,
                    use_openai_generation INTEGER NOT NULL,
                    openai_model TEXT NOT NULL,
                    knowledge_dir TEXT NOT NULL,
                    index_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    indexed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agents_org_company
                ON agents (org_id, company_id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_documents (
                    document_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    storage_provider TEXT NOT NULL DEFAULT 'local',
                    storage_key TEXT,
                    content_type TEXT,
                    checksum_sha256 TEXT,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    indexed_at TEXT,
                    error_message TEXT,
                    operational_section TEXT,
                    learning_summary TEXT,
                    summary_updated_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_documents_agent_created
                ON agent_documents (agent_id, created_at DESC)
                """
            )
            self._ensure_document_columns(conn)
            self._ensure_agent_columns(conn)

    @staticmethod
    def _ensure_agent_columns(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(agents)").fetchall()}
        if "clubhx_tenant_id" not in columns:
            conn.execute("ALTER TABLE agents ADD COLUMN clubhx_tenant_id TEXT")
        if "clubhx_shop_domain" not in columns:
            conn.execute("ALTER TABLE agents ADD COLUMN clubhx_shop_domain TEXT")

    @staticmethod
    def _ensure_document_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(agent_documents)").fetchall()
        }

        if "storage_provider" not in columns:
            conn.execute(
                "ALTER TABLE agent_documents ADD COLUMN storage_provider TEXT NOT NULL DEFAULT 'local'"
            )

        if "storage_key" not in columns:
            conn.execute(
                "ALTER TABLE agent_documents ADD COLUMN storage_key TEXT"
            )

        if "content_type" not in columns:
            conn.execute(
                "ALTER TABLE agent_documents ADD COLUMN content_type TEXT"
            )

        if "checksum_sha256" not in columns:
            conn.execute(
                "ALTER TABLE agent_documents ADD COLUMN checksum_sha256 TEXT"
            )

        if "operational_section" not in columns:
            conn.execute(
                "ALTER TABLE agent_documents ADD COLUMN operational_section TEXT"
            )

        if "learning_summary" not in columns:
            conn.execute(
                "ALTER TABLE agent_documents ADD COLUMN learning_summary TEXT"
            )

        if "summary_updated_at" not in columns:
            conn.execute(
                "ALTER TABLE agent_documents ADD COLUMN summary_updated_at TEXT"
            )

        conn.execute(
            """
            UPDATE agent_documents
            SET storage_key = stored_path
            WHERE storage_key IS NULL OR storage_key = ''
            """
        )

    @staticmethod
    def _row_to_agent(row: sqlite3.Row) -> AgentRecord:
        return AgentRecord(
            agent_id=row["agent_id"],
            org_id=row["org_id"],
            company_id=row["company_id"],
            name=row["name"],
            objective=row["objective"],
            tone=row["tone"],
            description=row["description"],
            rag_backend=row["rag_backend"],
            generation_provider=row["generation_provider"],
            use_openai_generation=bool(row["use_openai_generation"]),
            openai_model=row["openai_model"],
            knowledge_dir=row["knowledge_dir"],
            index_path=row["index_path"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            indexed_at=_parse_datetime(row["indexed_at"]),
            clubhx_tenant_id=(row["clubhx_tenant_id"] if "clubhx_tenant_id" in row.keys() else None) or None,
            clubhx_shop_domain=(row["clubhx_shop_domain"] if "clubhx_shop_domain" in row.keys() else None) or None,
        )

    @staticmethod
    def _row_to_document(row: sqlite3.Row) -> AgentDocumentRecord:
        return AgentDocumentRecord(
            document_id=row["document_id"],
            agent_id=row["agent_id"],
            filename=row["filename"],
            stored_path=row["stored_path"],
            storage_provider=row["storage_provider"],
            storage_key=row["storage_key"] or row["stored_path"],
            content_type=row["content_type"],
            checksum_sha256=row["checksum_sha256"],
            size_bytes=int(row["size_bytes"]),
            status=row["status"],
            indexed_at=_parse_datetime(row["indexed_at"]),
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            operational_section=row["operational_section"],
            learning_summary=row["learning_summary"],
            summary_updated_at=_parse_datetime(row["summary_updated_at"]),
        )

    def create_agent(
        self,
        org_id: str,
        company_id: str,
        name: str,
        objective: str,
        tone: str,
        description: str,
        rag_backend: str,
        generation_provider: str,
        use_openai_generation: bool,
        openai_model: str,
        knowledge_dir: str,
        index_path: str,
    ) -> AgentRecord:
        agent_id = uuid4().hex
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, org_id, company_id, name, objective, tone, description,
                    rag_backend, generation_provider, use_openai_generation, openai_model,
                    knowledge_dir, index_path, created_at, updated_at, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    org_id,
                    company_id,
                    name,
                    objective,
                    tone,
                    description,
                    rag_backend,
                    generation_provider,
                    int(use_openai_generation),
                    openai_model,
                    knowledge_dir,
                    index_path,
                    now,
                    now,
                    None,
                ),
            )

        return AgentRecord(
            agent_id=agent_id,
            org_id=org_id,
            company_id=company_id,
            name=name,
            objective=objective,
            tone=tone,
            description=description,
            rag_backend=rag_backend,
            generation_provider=generation_provider,
            use_openai_generation=use_openai_generation,
            openai_model=openai_model,
            knowledge_dir=knowledge_dir,
            index_path=index_path,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
            indexed_at=None,
        )

    def list_agents(self, org_ids: set[str], company_id: str | None = None) -> list[AgentRecord]:
        if not org_ids:
            return []

        placeholders = ",".join("?" for _ in org_ids)
        params: list[str] = list(org_ids)
        query = (
            f"SELECT * FROM agents WHERE org_id IN ({placeholders})"
        )
        if company_id is not None:
            query += " AND company_id = ?"
            params.append(company_id)
        query += " ORDER BY created_at ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_agent(row) for row in rows]

    def list_agents_with_document_counts(
        self, org_ids: set[str], company_id: str | None = None
    ) -> list[tuple[AgentRecord, int]]:
        if not org_ids:
            return []
        placeholders = ",".join("?" for _ in org_ids)
        params: list[str] = list(org_ids)
        query = (
            "SELECT a.*, COUNT(d.document_id) AS documents_count "
            "FROM agents a LEFT JOIN agent_documents d ON d.agent_id = a.agent_id "
            f"WHERE a.org_id IN ({placeholders})"
        )
        if company_id is not None:
            query += " AND a.company_id = ?"
            params.append(company_id)
        query += " GROUP BY a.agent_id ORDER BY a.created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [(self._row_to_agent(row), int(row["documents_count"] or 0)) for row in rows]

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_agent(row)

    def list_all_agents(self) -> list[AgentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT agent_id, org_id, company_id, name, objective, tone, description,
                       rag_backend, generation_provider, use_openai_generation, openai_model,
                       knowledge_dir, index_path, created_at, updated_at, indexed_at
                FROM agents
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [self._row_to_agent(row) for row in rows]

    def update_agent(self, agent: AgentRecord) -> AgentRecord:
        agent.updated_at = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agents
                SET
                    org_id = ?,
                    company_id = ?,
                    name = ?,
                    objective = ?,
                    tone = ?,
                    description = ?,
                    rag_backend = ?,
                    generation_provider = ?,
                    use_openai_generation = ?,
                    openai_model = ?,
                    knowledge_dir = ?,
                    index_path = ?,
                    updated_at = ?,
                    indexed_at = ?,
                    clubhx_tenant_id = ?,
                    clubhx_shop_domain = ?
                WHERE agent_id = ?
                """,
                (
                    agent.org_id,
                    agent.company_id,
                    agent.name,
                    agent.objective,
                    agent.tone,
                    agent.description,
                    agent.rag_backend,
                    agent.generation_provider,
                    int(agent.use_openai_generation),
                    agent.openai_model,
                    agent.knowledge_dir,
                    agent.index_path,
                    agent.updated_at.isoformat(),
                    agent.indexed_at.isoformat() if agent.indexed_at else None,
                    agent.clubhx_tenant_id or None,
                    agent.clubhx_shop_domain or None,
                    agent.agent_id,
                ),
            )
        return agent

    def delete_agent(self, agent_id: str) -> AgentRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            if row is None:
                return None

            conn.execute(
                "DELETE FROM agents WHERE agent_id = ?",
                (agent_id,),
            )

        return self._row_to_agent(row)

    def add_document(
        self,
        agent_id: str,
        filename: str,
        stored_path: str,
        size_bytes: int,
        storage_provider: str = "local",
        storage_key: str | None = None,
        content_type: str | None = None,
        checksum_sha256: str | None = None,
        operational_section: str | None = None,
        learning_summary: str | None = None,
    ) -> AgentDocumentRecord:
        document_id = uuid4().hex
        created_at = _utcnow_iso()
        effective_storage_key = storage_key or stored_path
        summary_updated_at = created_at if learning_summary else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_documents (
                    document_id, agent_id, filename, stored_path, storage_provider,
                    storage_key, content_type, checksum_sha256, size_bytes,
                    status, indexed_at, error_message, operational_section,
                    learning_summary, summary_updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    agent_id,
                    filename,
                    stored_path,
                    storage_provider,
                    effective_storage_key,
                    content_type,
                    checksum_sha256,
                    size_bytes,
                    "uploaded",
                    None,
                    None,
                    operational_section,
                    learning_summary,
                    summary_updated_at,
                    created_at,
                ),
            )

        return AgentDocumentRecord(
            document_id=document_id,
            agent_id=agent_id,
            filename=filename,
            stored_path=stored_path,
            storage_provider=storage_provider,
            storage_key=effective_storage_key,
            content_type=content_type,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
            status="uploaded",
            indexed_at=None,
            error_message=None,
            created_at=datetime.fromisoformat(created_at),
            operational_section=operational_section,
            learning_summary=learning_summary,
            summary_updated_at=datetime.fromisoformat(summary_updated_at)
            if summary_updated_at
            else None,
        )

    def list_documents(self, agent_id: str) -> list[AgentDocumentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_documents
                WHERE agent_id = ?
                ORDER BY created_at DESC
                """,
                (agent_id,),
            ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def delete_document(self, agent_id: str, document_id: str) -> AgentDocumentRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_documents
                WHERE agent_id = ? AND document_id = ?
                """,
                (agent_id, document_id),
            ).fetchone()
            if row is None:
                return None

            conn.execute(
                "DELETE FROM agent_documents WHERE document_id = ?",
                (document_id,),
            )
        return self._row_to_document(row)

    def mark_documents_indexed(self, agent_id: str) -> None:
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_documents
                SET status = ?, indexed_at = ?, error_message = NULL
                WHERE agent_id = ?
                """,
                ("indexed", now, agent_id),
            )

    def mark_documents_failed(self, agent_id: str, error_message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_documents
                SET status = ?, error_message = ?, indexed_at = NULL
                WHERE agent_id = ? AND status <> ?
                """,
                ("failed", error_message, agent_id, "indexed"),
            )
