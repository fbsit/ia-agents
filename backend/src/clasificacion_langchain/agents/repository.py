from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4


@dataclass
class AgentRecord:
    agent_id: str
    org_id: str
    company_id: str
    name: str
    objective: str
    tone: str
    description: str
    rag_backend: str
    generation_provider: str
    use_openai_generation: bool
    openai_model: str
    knowledge_dir: str
    index_path: str
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None = None
    # Integracion de comercio (ClubHx/whsflow): tenant y dominio de la tienda conectada.
    clubhx_tenant_id: str | None = None
    clubhx_shop_domain: str | None = None


@dataclass
class AgentDocumentRecord:
    document_id: str
    agent_id: str
    filename: str
    stored_path: str
    storage_provider: str
    storage_key: str
    content_type: str | None
    checksum_sha256: str | None
    size_bytes: int
    status: str
    indexed_at: datetime | None
    error_message: str | None
    created_at: datetime
    operational_section: str | None = None
    learning_summary: str | None = None
    summary_updated_at: datetime | None = None


class AgentRepository(Protocol):
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
        ...

    def list_agents(self, org_ids: set[str], company_id: str | None = None) -> list[AgentRecord]:
        ...

    def list_agents_with_document_counts(
        self, org_ids: set[str], company_id: str | None = None
    ) -> list[tuple[AgentRecord, int]]:
        """Listado + cantidad de documentos en una sola consulta (evita N+1 contra bases remotas)."""
        ...

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        ...

    def list_all_agents(self) -> list[AgentRecord]:
        ...

    def update_agent(self, agent: AgentRecord) -> AgentRecord:
        ...

    def delete_agent(self, agent_id: str) -> AgentRecord | None:
        ...

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
        ...

    def list_documents(self, agent_id: str) -> list[AgentDocumentRecord]:
        ...

    def delete_document(self, agent_id: str, document_id: str) -> AgentDocumentRecord | None:
        ...

    def mark_documents_indexed(self, agent_id: str) -> None:
        ...

    def mark_documents_failed(self, agent_id: str, error_message: str) -> None:
        ...


@dataclass
class InMemoryAgentRepository:
    agents_by_id: dict[str, AgentRecord] = field(default_factory=dict)
    documents_by_agent: dict[str, list[AgentDocumentRecord]] = field(default_factory=dict)

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
        now = datetime.now(UTC)
        agent = AgentRecord(
            agent_id=uuid4().hex,
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
        )
        self.agents_by_id[agent.agent_id] = agent
        return agent

    def list_agents(self, org_ids: set[str], company_id: str | None = None) -> list[AgentRecord]:
        result: list[AgentRecord] = []
        for agent in self.agents_by_id.values():
            if agent.org_id not in org_ids:
                continue
            if company_id and agent.company_id != company_id:
                continue
            result.append(agent)

        result.sort(key=lambda item: item.created_at)
        return result

    def list_agents_with_document_counts(
        self, org_ids: set[str], company_id: str | None = None
    ) -> list[tuple[AgentRecord, int]]:
        return [
            (agent, len(self.documents_by_agent.get(agent.agent_id, [])))
            for agent in self.list_agents(org_ids, company_id=company_id)
        ]

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        return self.agents_by_id.get(agent_id)

    def list_all_agents(self) -> list[AgentRecord]:
        result = list(self.agents_by_id.values())
        result.sort(key=lambda item: item.created_at)
        return result

    def update_agent(self, agent: AgentRecord) -> AgentRecord:
        agent.updated_at = datetime.now(UTC)
        self.agents_by_id[agent.agent_id] = agent
        return agent

    def delete_agent(self, agent_id: str) -> AgentRecord | None:
        removed = self.agents_by_id.pop(agent_id, None)
        self.documents_by_agent.pop(agent_id, None)
        return removed

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
        now = datetime.now(UTC)
        document = AgentDocumentRecord(
            document_id=uuid4().hex,
            agent_id=agent_id,
            filename=filename,
            stored_path=stored_path,
            storage_provider=storage_provider,
            storage_key=storage_key or stored_path,
            content_type=content_type,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
            status="uploaded",
            indexed_at=None,
            error_message=None,
            created_at=now,
            operational_section=operational_section,
            learning_summary=learning_summary,
            summary_updated_at=now if learning_summary else None,
        )
        self.documents_by_agent.setdefault(agent_id, []).append(document)
        return document

    def list_documents(self, agent_id: str) -> list[AgentDocumentRecord]:
        documents = self.documents_by_agent.get(agent_id, [])
        return sorted(documents, key=lambda item: item.created_at, reverse=True)

    def delete_document(self, agent_id: str, document_id: str) -> AgentDocumentRecord | None:
        documents = self.documents_by_agent.get(agent_id, [])
        for idx, document in enumerate(documents):
            if document.document_id != document_id:
                continue
            removed = documents.pop(idx)
            self.documents_by_agent[agent_id] = documents
            return removed
        return None

    def mark_documents_indexed(self, agent_id: str) -> None:
        documents = self.documents_by_agent.get(agent_id, [])
        now = datetime.now(UTC)
        for document in documents:
            document.status = "indexed"
            document.indexed_at = now
            document.error_message = None

    def mark_documents_failed(self, agent_id: str, error_message: str) -> None:
        documents = self.documents_by_agent.get(agent_id, [])
        for document in documents:
            if document.status == "indexed":
                continue
            document.status = "failed"
            document.error_message = error_message
