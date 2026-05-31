from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from clasificacion_langchain.rag.embeddings import OpenAIEmbeddingClient
from clasificacion_langchain.rag.schemas import ChunkedDocument, RetrievedChunk


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return matrix.astype(np.float32)

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    normalized = matrix / norms
    return normalized.astype(np.float32)


@dataclass
class DenseVectorIndex:
    embeddings: np.ndarray
    chunks: list[ChunkedDocument]
    embedding_model: str
    provider: str = "openai"
    timeout_seconds: int = 60
    api_key: str | None = None

    def __post_init__(self) -> None:
        if self.provider != "openai":
            raise ValueError(f"Proveedor de embeddings no soportado: {self.provider}")
        self.embeddings = _normalize_rows(self.embeddings)
        self._embedder = OpenAIEmbeddingClient(
            model=self.embedding_model,
            timeout_seconds=self.timeout_seconds,
            api_key=self.api_key,
        )

    @classmethod
    def build(
        cls,
        chunks: list[ChunkedDocument],
        embedding_model: str = "text-embedding-3-small",
        batch_size: int = 64,
        timeout_seconds: int = 60,
        api_key: str | None = None,
    ) -> "DenseVectorIndex":
        if not chunks:
            raise ValueError("No hay chunks para indexar")
        if batch_size <= 0:
            raise ValueError("batch_size debe ser mayor a 0")

        embedder = OpenAIEmbeddingClient(
            model=embedding_model,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )

        vectors: list[np.ndarray] = []
        texts = [chunk.text for chunk in chunks]
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            vectors.append(embedder.embed_texts(batch))

        embeddings = np.vstack(vectors).astype(np.float32)
        return cls(
            embeddings=embeddings,
            chunks=chunks,
            embedding_model=embedding_model,
            provider="openai",
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )

    def save(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "index_type": "dense_openai",
                "embeddings": self.embeddings,
                "chunks": self.chunks,
                "embedding_model": self.embedding_model,
                "provider": self.provider,
                "timeout_seconds": self.timeout_seconds,
            },
            path,
        )
        return path

    @classmethod
    def load(
        cls,
        index_path: str | Path,
        api_key: str | None = None,
    ) -> "DenseVectorIndex":
        path = Path(index_path)
        if not path.exists():
            raise FileNotFoundError(
                f"No existe indice RAG en {path}. Ejecuta build_rag_index.py primero."
            )

        artifact = joblib.load(path)
        if artifact.get("index_type") != "dense_openai":
            raise ValueError("El artefacto no corresponde a DenseVectorIndex")

        return cls(
            embeddings=artifact["embeddings"],
            chunks=artifact["chunks"],
            embedding_model=artifact["embedding_model"],
            provider=artifact.get("provider", "openai"),
            timeout_seconds=int(artifact.get("timeout_seconds", 60)),
            api_key=api_key,
        )

    def search(
        self,
        query: str,
        company_id: str,
        top_k: int = 4,
        min_score: float = 0.05,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []

        company_indices = [
            idx for idx, chunk in enumerate(self.chunks) if chunk.company_id == company_id
        ]
        if not company_indices:
            return []

        query_vector = self._embedder.embed_texts([query])
        query_vector = _normalize_rows(query_vector)[0]

        company_embeddings = self.embeddings[company_indices]
        similarities = np.dot(company_embeddings, query_vector)

        sorted_positions = np.argsort(similarities)[::-1]
        retrieved: list[RetrievedChunk] = []

        for rank in sorted_positions[:top_k]:
            score = float(similarities[rank])
            if score < min_score:
                continue

            chunk = self.chunks[company_indices[int(rank)]]
            retrieved.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    company_id=chunk.company_id,
                    source=chunk.source,
                    text=chunk.text,
                    score=score,
                    position=chunk.position,
                )
            )

        return retrieved
