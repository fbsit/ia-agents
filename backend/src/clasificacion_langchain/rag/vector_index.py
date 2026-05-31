from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from clasificacion_langchain.rag.schemas import ChunkedDocument, RetrievedChunk


@dataclass
class TfidfVectorIndex:
    vectorizer: TfidfVectorizer
    matrix: object
    chunks: list[ChunkedDocument]

    @classmethod
    def build(
        cls,
        chunks: list[ChunkedDocument],
        max_features: int = 20000,
        min_df: int = 1,
    ) -> "TfidfVectorIndex":
        if not chunks:
            raise ValueError("No hay chunks para indexar")

        vectorizer = TfidfVectorizer(
            max_features=max_features,
            ngram_range=(1, 2),
            min_df=min_df,
        )
        matrix = vectorizer.fit_transform([chunk.text for chunk in chunks])
        return cls(vectorizer=vectorizer, matrix=matrix, chunks=chunks)

    def save(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "index_type": "tfidf",
                "vectorizer": self.vectorizer,
                "matrix": self.matrix,
                "chunks": self.chunks,
            },
            path,
        )
        return path

    @classmethod
    def load(cls, index_path: str | Path) -> "TfidfVectorIndex":
        path = Path(index_path)
        if not path.exists():
            raise FileNotFoundError(
                f"No existe indice RAG en {path}. Ejecuta build_rag_index.py primero."
            )

        artifact = joblib.load(path)

        if "vectorizer" not in artifact or "matrix" not in artifact or "chunks" not in artifact:
            raise ValueError("El artefacto no corresponde a TfidfVectorIndex")

        return cls(
            vectorizer=artifact["vectorizer"],
            matrix=artifact["matrix"],
            chunks=artifact["chunks"],
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

        company_matrix = self.matrix[company_indices]
        query_vector = self.vectorizer.transform([query])
        similarities = cosine_similarity(query_vector, company_matrix)[0]

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
