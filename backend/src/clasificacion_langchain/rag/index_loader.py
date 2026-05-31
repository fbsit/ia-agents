from __future__ import annotations

from pathlib import Path

import joblib

from clasificacion_langchain.rag.dense_index import DenseVectorIndex
from clasificacion_langchain.rag.hybrid_index import HybridVectorIndex
from clasificacion_langchain.rag.vector_index import TfidfVectorIndex


def load_index(index_path: str | Path):
    path = Path(index_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No existe indice RAG en {path}. Ejecuta build_rag_index.py primero."
        )

    artifact = joblib.load(path)
    index_type = artifact.get("index_type", "") if isinstance(artifact, dict) else ""

    if index_type == "dense_openai":
        return DenseVectorIndex.load(path)

    if index_type == "hybrid_openai":
        return HybridVectorIndex.load(path)

    return TfidfVectorIndex.load(path)
