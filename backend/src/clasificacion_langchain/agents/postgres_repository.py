from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from clasificacion_langchain.agents.repository import AgentDocumentRecord, AgentRecord
from clasificacion_langchain.persistence.pg_connections import pooled_connection


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


class PostgresAgentRepository:
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
                        use_openai_generation BOOLEAN NOT NULL,
                        openai_model TEXT NOT NULL,
                        knowledge_dir TEXT NOT NULL,
                        index_path TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        indexed_at TIMESTAMPTZ
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agents_org_company ON agents (org_id, company_id)"
                )
                cur.execute(
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
                        size_bytes BIGINT NOT NULL,
                        status TEXT NOT NULL,
                        indexed_at TIMESTAMPTZ,
                        error_message TEXT,
                        operational_section TEXT,
                        learning_summary TEXT,
                        summary_updated_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL,
                        FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agent_documents_agent_created ON agent_documents (agent_id, created_at DESC)"
                )
                cur.execute(
                    "ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS storage_provider TEXT NOT NULL DEFAULT 'local'"
                )
                cur.execute(
                    "ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS storage_key TEXT"
                )
                cur.execute(
                    "ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS content_type TEXT"
                )
                cur.execute(
                    "ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS checksum_sha256 TEXT"
                )
                cur.execute(
                    "ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS operational_section TEXT"
                )
                cur.execute(
                    "ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS learning_summary TEXT"
                )
                cur.execute(
                    "ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS summary_updated_at TIMESTAMPTZ"
                )
                cur.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS clubhx_tenant_id TEXT")
                cur.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS clubhx_shop_domain TEXT")
                cur.execute(
                    """
                    UPDATE agent_documents
                    SET storage_key = stored_path
                    WHERE storage_key IS NULL OR storage_key = ''
                    """
                )
            conn.commit()

    @staticmethod
    def _row_to_agent(row: tuple) -> AgentRecord:
        return AgentRecord(
            agent_id=row[0],
            org_id=row[1],
            company_id=row[2],
            name=row[3],
            objective=row[4],
            tone=row[5],
            description=row[6],
            rag_backend=row[7],
            generation_provider=row[8],
            use_openai_generation=bool(row[9]),
            openai_model=row[10],
            knowledge_dir=row[11],
            index_path=row[12],
            created_at=_parse_datetime(row[13]) or _utcnow(),
            updated_at=_parse_datetime(row[14]) or _utcnow(),
            indexed_at=_parse_datetime(row[15]),
            clubhx_tenant_id=(row[16] if len(row) > 16 else None) or None,
            clubhx_shop_domain=(row[17] if len(row) > 17 else None) or None,
        )

    @staticmethod
    def _row_to_document(row: tuple) -> AgentDocumentRecord:
        return AgentDocumentRecord(
            document_id=row[0],
            agent_id=row[1],
            filename=row[2],
            stored_path=row[3],
            storage_provider=row[4],
            storage_key=row[5] or row[3],
            content_type=row[6],
            checksum_sha256=row[7],
            size_bytes=int(row[8]),
            status=row[9],
            indexed_at=_parse_datetime(row[10]),
            error_message=row[11],
            operational_section=row[12],
            learning_summary=row[13],
            summary_updated_at=_parse_datetime(row[14]),
            created_at=_parse_datetime(row[15]) or _utcnow(),
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
        now = _utcnow()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agents (
                        agent_id, org_id, company_id, name, objective, tone, description,
                        rag_backend, generation_provider, use_openai_generation, openai_model,
                        knowledge_dir, index_path, created_at, updated_at, indexed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        use_openai_generation,
                        openai_model,
                        knowledge_dir,
                        index_path,
                        now,
                        now,
                        None,
                    ),
                )
            conn.commit()

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
            created_at=now,
            updated_at=now,
            indexed_at=None,
        )

    def list_agents(self, org_ids: set[str], company_id: str | None = None) -> list[AgentRecord]:
        if not org_ids:
            return []

        if company_id is not None:
            query = (
                "SELECT * FROM agents WHERE org_id = ANY(%s) AND company_id = %s ORDER BY created_at ASC"
            )
            params = (list(org_ids), company_id)
        else:
            query = "SELECT * FROM agents WHERE org_id = ANY(%s) ORDER BY created_at ASC"
            params = (list(org_ids),)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [self._row_to_agent(row) for row in rows]

    def list_agents_with_document_counts(
        self, org_ids: set[str], company_id: str | None = None
    ) -> list[tuple[AgentRecord, int]]:
        if not org_ids:
            return []
        # a.* conserva el orden de columnas que espera _row_to_agent; el COUNT va al final.
        query = (
            "SELECT a.*, COUNT(d.document_id) AS documents_count "
            "FROM agents a LEFT JOIN agent_documents d ON d.agent_id = a.agent_id "
            "WHERE a.org_id = ANY(%s)"
        )
        params: list[object] = [list(org_ids)]
        if company_id is not None:
            query += " AND a.company_id = %s"
            params.append(company_id)
        query += " GROUP BY a.agent_id ORDER BY a.created_at ASC"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [(self._row_to_agent(row), int(row[-1] or 0)) for row in rows]

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM agents WHERE agent_id = %s", (agent_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_agent(row)

    def list_all_agents(self) -> list[AgentRecord]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT agent_id, org_id, company_id, name, objective, tone, description,
                           rag_backend, generation_provider, use_openai_generation, openai_model,
                           knowledge_dir, index_path, created_at::text, updated_at::text, indexed_at::text
                    FROM {self.schema}.agents
                    ORDER BY created_at ASC
                    """
                )
                rows = cur.fetchall()
        return [self._row_to_agent(row) for row in rows]

    def update_agent(self, agent: AgentRecord) -> AgentRecord:
        agent.updated_at = _utcnow()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agents
                    SET
                        org_id = %s,
                        company_id = %s,
                        name = %s,
                        objective = %s,
                        tone = %s,
                        description = %s,
                        rag_backend = %s,
                        generation_provider = %s,
                        use_openai_generation = %s,
                        openai_model = %s,
                        knowledge_dir = %s,
                        index_path = %s,
                        updated_at = %s,
                        indexed_at = %s,
                        clubhx_tenant_id = %s,
                        clubhx_shop_domain = %s
                    WHERE agent_id = %s
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
                        agent.use_openai_generation,
                        agent.openai_model,
                        agent.knowledge_dir,
                        agent.index_path,
                        agent.updated_at,
                        agent.indexed_at,
                        agent.clubhx_tenant_id or None,
                        agent.clubhx_shop_domain or None,
                        agent.agent_id,
                    ),
                )
            conn.commit()
        return agent

    def delete_agent(self, agent_id: str) -> AgentRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM agents WHERE agent_id = %s", (agent_id,))
                row = cur.fetchone()
                if row is None:
                    return None
                cur.execute("DELETE FROM agents WHERE agent_id = %s", (agent_id,))
            conn.commit()
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
        created_at = _utcnow()
        effective_storage_key = storage_key or stored_path
        summary_updated_at = created_at if learning_summary else None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_documents (
                        document_id, agent_id, filename, stored_path, storage_provider,
                        storage_key, content_type, checksum_sha256, size_bytes,
                        status, indexed_at, error_message, operational_section,
                        learning_summary, summary_updated_at, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            conn.commit()

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
            created_at=created_at,
            operational_section=operational_section,
            learning_summary=learning_summary,
            summary_updated_at=summary_updated_at,
        )

    def list_documents(self, agent_id: str) -> list[AgentDocumentRecord]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM agent_documents
                    WHERE agent_id = %s
                    ORDER BY created_at DESC
                    """,
                    (agent_id,),
                )
                rows = cur.fetchall()
        return [self._row_to_document(row) for row in rows]

    def delete_document(self, agent_id: str, document_id: str) -> AgentDocumentRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM agent_documents
                    WHERE agent_id = %s AND document_id = %s
                    """,
                    (agent_id, document_id),
                )
                row = cur.fetchone()
                if row is None:
                    return None

                cur.execute(
                    "DELETE FROM agent_documents WHERE document_id = %s",
                    (document_id,),
                )
            conn.commit()
        return self._row_to_document(row)

    def mark_documents_indexed(self, agent_id: str) -> None:
        now = _utcnow()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_documents
                    SET status = %s, indexed_at = %s, error_message = NULL
                    WHERE agent_id = %s
                    """,
                    ("indexed", now, agent_id),
                )
            conn.commit()

    def mark_documents_failed(self, agent_id: str, error_message: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_documents
                    SET status = %s, error_message = %s, indexed_at = NULL
                    WHERE agent_id = %s AND status <> %s
                    """,
                    ("failed", error_message, agent_id, "indexed"),
                )
            conn.commit()
