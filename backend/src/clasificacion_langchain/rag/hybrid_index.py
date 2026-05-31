from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib

from clasificacion_langchain.rag.dense_index import DenseVectorIndex
from clasificacion_langchain.rag.schemas import ChunkedDocument, RetrievedChunk
from clasificacion_langchain.rag.vector_index import TfidfVectorIndex


@dataclass
class HybridVectorIndex:
    tfidf_index: TfidfVectorIndex
    dense_index: DenseVectorIndex
    rrf_k: int = 60

    @classmethod
    def build(
        cls,
        chunks: list[ChunkedDocument],
        max_features: int = 20000,
        embedding_model: str = "text-embedding-3-small",
        embedding_batch_size: int = 64,
        embedding_timeout_seconds: int = 60,
        api_key: str | None = None,
        rrf_k: int = 60,
    ) -> "HybridVectorIndex":
        tfidf_index = TfidfVectorIndex.build(chunks, max_features=max_features)
        dense_index = DenseVectorIndex.build(
            chunks,
            embedding_model=embedding_model,
            batch_size=embedding_batch_size,
            timeout_seconds=embedding_timeout_seconds,
            api_key=api_key,
        )
        return cls(tfidf_index=tfidf_index, dense_index=dense_index, rrf_k=max(1, rrf_k))

    def save(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "index_type": "hybrid_openai",
                "rrf_k": self.rrf_k,
                "tfidf": {
                    "vectorizer": self.tfidf_index.vectorizer,
                    "matrix": self.tfidf_index.matrix,
                    "chunks": self.tfidf_index.chunks,
                },
                "dense": {
                    "embeddings": self.dense_index.embeddings,
                    "chunks": self.dense_index.chunks,
                    "embedding_model": self.dense_index.embedding_model,
                    "provider": self.dense_index.provider,
                    "timeout_seconds": self.dense_index.timeout_seconds,
                },
            },
            path,
        )
        return path

    @classmethod
    def load(
        cls,
        index_path: str | Path,
        api_key: str | None = None,
    ) -> "HybridVectorIndex":
        path = Path(index_path)
        if not path.exists():
            raise FileNotFoundError(
                f"No existe indice RAG en {path}. Ejecuta build_rag_index.py primero."
            )

        artifact = joblib.load(path)
        if artifact.get("index_type") != "hybrid_openai":
            raise ValueError("El artefacto no corresponde a HybridVectorIndex")

        tfidf_artifact = artifact.get("tfidf") or {}
        dense_artifact = artifact.get("dense") or {}

        tfidf_index = TfidfVectorIndex(
            vectorizer=tfidf_artifact["vectorizer"],
            matrix=tfidf_artifact["matrix"],
            chunks=tfidf_artifact["chunks"],
        )
        dense_index = DenseVectorIndex(
            embeddings=dense_artifact["embeddings"],
            chunks=dense_artifact["chunks"],
            embedding_model=dense_artifact["embedding_model"],
            provider=dense_artifact.get("provider", "openai"),
            timeout_seconds=int(dense_artifact.get("timeout_seconds", 60)),
            api_key=api_key,
        )
        return cls(tfidf_index=tfidf_index, dense_index=dense_index, rrf_k=int(artifact.get("rrf_k", 60)))

    def search(
        self,
        query: str,
        company_id: str,
        top_k: int = 4,
        min_score: float = 0.05,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []

        candidate_limit = max(top_k * 4, top_k)
        tfidf_hits = self.tfidf_index.search(
            query=query,
            company_id=company_id,
            top_k=candidate_limit,
            min_score=min_score,
        )
        dense_hits = self.dense_index.search(
            query=query,
            company_id=company_id,
            top_k=candidate_limit,
            min_score=min_score,
        )

        if not tfidf_hits and not dense_hits:
            return []

        fused_scores: dict[str, float] = {}
        chunk_lookup: dict[str, RetrievedChunk] = {}

        for rank, chunk in enumerate(tfidf_hits):
            chunk_lookup.setdefault(chunk.chunk_id, chunk)
            fused_scores[chunk.chunk_id] = fused_scores.get(chunk.chunk_id, 0.0) + 1.0 / (
                self.rrf_k + rank + 1
            )

        for rank, chunk in enumerate(dense_hits):
            chunk_lookup.setdefault(chunk.chunk_id, chunk)
            fused_scores[chunk.chunk_id] = fused_scores.get(chunk.chunk_id, 0.0) + 1.0 / (
                self.rrf_k + rank + 1
            )

        sorted_chunk_ids = sorted(
            fused_scores.keys(),
            key=lambda chunk_id: fused_scores[chunk_id],
            reverse=True,
        )

        merged: list[RetrievedChunk] = []
        for chunk_id in sorted_chunk_ids[:top_k]:
            base = chunk_lookup[chunk_id]
            merged.append(
                RetrievedChunk(
                    chunk_id=base.chunk_id,
                    company_id=base.company_id,
                    source=base.source,
                    text=base.text,
                    score=float(fused_scores[chunk_id]),
                    position=base.position,
                )
            )

        return merged
