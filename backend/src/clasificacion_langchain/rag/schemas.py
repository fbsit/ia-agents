from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KnowledgeDocument:
    company_id: str
    source: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ChunkedDocument:
    chunk_id: str
    company_id: str
    source: str
    text: str
    position: int
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    chunk_id: str
    company_id: str
    source: str
    text: str
    score: float
    position: int


@dataclass
class RAGAnswer:
    answer: str
    company_id: str
    sources: list[str]
    retrieved_chunks: list[RetrievedChunk]
    intent_label: str | None = None
    route: str | None = None
    route_reason: str | None = None
    response_mode: str | None = None
    fallback_applied: bool = False
    retrieval_min_score: float | None = None
