from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from clasificacion_langchain.rag.dense_index import DenseVectorIndex
from clasificacion_langchain.rag.hybrid_index import HybridVectorIndex
from clasificacion_langchain.rag.chunking import chunk_documents
from clasificacion_langchain.rag.generation import (
    AnswerGenerator,
    ExtractiveAnswerGenerator,
    build_remote_generator,
    is_remote_generator,
    tune_answer_style,
)
from clasificacion_langchain.rag.index_loader import load_index
from clasificacion_langchain.rag.loaders import load_company_documents
from clasificacion_langchain.rag.schemas import RAGAnswer
from clasificacion_langchain.rag.vector_index import TfidfVectorIndex
from clasificacion_langchain.settings.service import TenantLlmSettingsService
from clasificacion_langchain.settings.sqlite_store import SQLiteTenantLlmSettingsStore
from clasificacion_langchain.settings.service import TenantLlmSettingsStore

logger = logging.getLogger(__name__)


class RetrievalIndex(Protocol):
    def search(
        self,
        query: str,
        company_id: str,
        top_k: int = 4,
        min_score: float = 0.05,
    ) -> list:
        ...


@dataclass
class IndexBuildResult:
    index_path: Path
    total_documents: int
    total_chunks: int
    companies: list[str]
    backend: str


class RAGPipeline:
    def __init__(self, index: RetrievalIndex, generator: AnswerGenerator) -> None:
        self.index = index
        self.generator = generator

    @classmethod
    def from_artifact(
        cls,
        index_path: str | Path,
        use_openai: bool = False,
        openai_model: str = "gpt-4o-mini",
        generation_provider: str = "auto",
        anthropic_model: str = "claude-sonnet-4-6",
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
    ) -> "RAGPipeline":
        index = load_index(index_path)
        generator: AnswerGenerator
        remote_generator = build_remote_generator(
            model=openai_model,
            generation_provider=generation_provider,
            anthropic_model=anthropic_model,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )
        llm_available = remote_generator is not None

        if use_openai and llm_available:
            generator = remote_generator
        else:
            generator = ExtractiveAnswerGenerator(
                openai_requested=use_openai,
                openai_available=llm_available,
            )

        return cls(index=index, generator=generator)

    def answer(
        self,
        query: str,
        company_id: str,
        top_k: int = 4,
        min_score: float = 0.05,
        objective: str | None = None,
        tone: str | None = None,
        generation_provider: str | None = None,
        generation_model: str | None = None,
        use_openai_generation: bool | None = None,
    ) -> RAGAnswer:
        chunks = self.index.search(
            query=query,
            company_id=company_id,
            top_k=top_k,
            min_score=min_score,
        )

        generator = self.generator
        if generation_provider or generation_model or use_openai_generation is not None:
            from clasificacion_langchain.settings.service import TenantLlmSettingsService

            normalized_company_id = company_id.strip().lower()
            logger.info(
                "rag_pipeline_answer_debug company_id_raw=%s company_id_normalized=%s",
                company_id,
                normalized_company_id,
            )
            settings_service = TenantLlmSettingsService(store=SQLiteTenantLlmSettingsStore())
            settings = settings_service.get(normalized_company_id)
            openai_api_key = settings.openai_api_key if settings and settings.openai_api_key else None
            anthropic_api_key = settings.anthropic_api_key if settings and settings.anthropic_api_key else None

            logger.info(
                "rag_pipeline_answer_debug company_id=%s provider=%s model=%s use_openai=%s "
                "has_openai_key=%s has_anthropic_key=%s",
                company_id,
                generation_provider,
                generation_model,
                use_openai_generation,
                bool(openai_api_key),
                bool(anthropic_api_key),
            )

            runtime_generator = build_remote_generator(
                model=generation_model or "gpt-4o-mini",
                generation_provider=generation_provider or "auto",
                anthropic_model=generation_model or "claude-sonnet-4-6",
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
            )
            logger.info(
                "rag_pipeline_runtime_generator company_id=%s generator=%s chunks=%s",
                company_id,
                type(runtime_generator).__name__ if runtime_generator else None,
                len(chunks),
            )
            use_llm = use_openai_generation or generation_provider in {"openai", "anthropic"}
            if use_llm and runtime_generator:
                generator = runtime_generator
            elif use_llm:
                generator = ExtractiveAnswerGenerator(
                    openai_requested=True,
                    openai_available=False,
                )

        if not chunks and is_remote_generator(generator):
            logger.info(
                "rag_pipeline_no_chunks_using_llm company_id=%s generator=%s",
                company_id,
                type(generator).__name__,
            )
            try:
                answer_text = generator.generate(
                    query=query,
                    chunks=[],
                    objective=objective,
                    tone=tone,
                )
                return RAGAnswer(
                    answer=answer_text,
                    company_id=company_id,
                    sources=[],
                    retrieved_chunks=[],
                )
            except RuntimeError as exc:
                logger.warning(
                    "rag_remote_generation_no_chunks_failed company_id=%s detail=%s",
                    company_id,
                    exc,
                )
                return RAGAnswer(
                    answer="No tengo conocimiento cargado sobre el tema. Pero puedo ayudarte directamente: " + query,
                    company_id=company_id,
                    sources=[],
                    retrieved_chunks=[],
                )

        try:
            answer_text = generator.generate(
                query=query,
                chunks=chunks,
                objective=objective,
                tone=tone,
            )
        except RuntimeError as exc:
            if not is_remote_generator(generator):
                raise

            logger.warning(
                "rag_remote_generation_failed model=%s detail=%s",
                getattr(generator, "model", "unknown"),
                exc,
            )

            fallback_generator = ExtractiveAnswerGenerator(
                openai_requested=False,
                openai_available=False,
            )
            fallback_answer = fallback_generator.generate(
                query=query,
                chunks=chunks,
                objective=objective,
                tone=tone,
            )
            answer_text = (
                "Nota: el proveedor LLM no estuvo disponible temporalmente, respondo en modo "
                "extractivo con evidencia.\n"
                f"{fallback_answer}"
            )
        answer_text = tune_answer_style(answer_text, query=query)
        sources = sorted({chunk.source for chunk in chunks})

        return RAGAnswer(
            answer=answer_text,
            company_id=company_id,
            sources=sources,
            retrieved_chunks=chunks,
        )


def build_and_save_index(
    knowledge_dir: str | Path,
    index_path: str | Path = "models/rag_index.joblib",
    backend: str = "tfidf",
    chunk_size: int = 900,
    chunk_overlap: int = 120,
    max_features: int = 20000,
    embedding_model: str = "text-embedding-3-small",
    embedding_batch_size: int = 64,
    openai_api_key: str | None = None,
) -> IndexBuildResult:
    requested_backend = backend.strip().lower()
    auto_requested = requested_backend == "auto"
    selected_backend = requested_backend
    if selected_backend == "auto":
        key_available = bool(openai_api_key or os.getenv("OPENAI_API_KEY", ""))
        selected_backend = "dense_openai" if key_available else "tfidf"

    documents = load_company_documents(knowledge_dir)
    chunks = chunk_documents(
        documents,
        chunk_size=chunk_size,
        overlap=chunk_overlap,
    )

    if selected_backend == "hybrid":
        try:
            index = HybridVectorIndex.build(
                chunks,
                max_features=max_features,
                embedding_model=embedding_model,
                embedding_batch_size=embedding_batch_size,
                api_key=openai_api_key,
            )
        except RuntimeError:
            if not auto_requested:
                raise
            index = TfidfVectorIndex.build(chunks, max_features=max_features)
            selected_backend = "tfidf"
    elif selected_backend == "dense_openai":
        try:
            index = DenseVectorIndex.build(
                chunks,
                embedding_model=embedding_model,
                batch_size=embedding_batch_size,
                api_key=openai_api_key,
            )
        except RuntimeError:
            if not auto_requested:
                raise
            index = TfidfVectorIndex.build(chunks, max_features=max_features)
            selected_backend = "tfidf"
    else:
        index = TfidfVectorIndex.build(chunks, max_features=max_features)

    saved_path = index.save(index_path)

    company_ids = sorted({document.company_id for document in documents})
    return IndexBuildResult(
        index_path=saved_path,
        total_documents=len(documents),
        total_chunks=len(chunks),
        companies=company_ids,
        backend=selected_backend,
    )
