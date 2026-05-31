from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from clasificacion_langchain.agents.repository import InMemoryAgentRepository  # noqa: E402
from clasificacion_langchain.agents.service import AgentService  # noqa: E402


def _build_service() -> AgentService:
    temp_root = Path(tempfile.gettempdir()) / f"svc-upsert-{uuid.uuid4().hex}"
    repository = InMemoryAgentRepository()
    return AgentService(
        repository=repository,
        knowledge_root=temp_root / "knowledge",
        index_root=temp_root / "index",
    )


def _build_agent(service: AgentService):
    return service.create_agent(
        org_id="org-test",
        company_id="kronix",
        name="Kronix Agent",
        objective="Responder consultas de operaciones",
        tone="operativo",
        description="",
        rag_backend="tfidf",
        generation_provider="auto",
        use_openai_generation=False,
        openai_model="gpt-4o-mini",
    )


def test_upsert_replaces_timestamped_filename_variant() -> None:
    service = _build_service()
    agent = _build_agent(service)

    first = service.save_document(
        agent=agent,
        filename="20260404T020745-facts-canonicos.md",
        content=b"version antigua",
    )
    second = service.save_document(
        agent=agent,
        filename="facts-canonicos.md",
        content=b"version nueva",
    )

    documents = service.list_documents(agent.agent_id)
    assert len(documents) == 1
    assert documents[0].document_id == second.document_id
    assert documents[0].document_id != first.document_id
    assert documents[0].filename == "facts-canonicos.md"


def test_upsert_replaces_previous_same_filename_content() -> None:
    service = _build_service()
    agent = _build_agent(service)

    service.save_document(
        agent=agent,
        filename="rules-decision-table.md",
        content=b"if role=owner then approve",
    )
    latest = service.save_document(
        agent=agent,
        filename="rules-decision-table.md",
        content=b"if role=owner and amount<=50000 then approve",
    )

    documents = service.list_documents(agent.agent_id)
    assert len(documents) == 1
    stored_bytes = service.document_storage.read(documents[0])
    assert b"amount<=50000" in stored_bytes
    assert documents[0].document_id == latest.document_id
