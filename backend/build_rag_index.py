from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.rag.pipeline import build_and_save_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Construye indice RAG multiempresa con TF-IDF"
    )
    parser.add_argument(
        "--knowledge-dir",
        default="knowledge_base",
        help="Directorio con estructura knowledge_base/<company_id>/...",
    )
    parser.add_argument(
        "--index-path",
        default="models/rag_index.joblib",
        help="Ruta de salida del indice",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "tfidf", "dense_openai", "hybrid"],
        default="auto",
        help="Backend de recuperacion para RAG",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=900,
        help="Tamano de chunk en caracteres",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=120,
        help="Solapamiento entre chunks",
    )
    parser.add_argument(
        "--max-features",
        type=int,
        default=20000,
        help="Maximo de features TF-IDF",
    )
    parser.add_argument(
        "--embedding-model",
        default="text-embedding-3-small",
        help="Modelo de embedding si backend=dense_openai o hybrid",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=64,
        help="Tamano de batch para embeddings",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_and_save_index(
        knowledge_dir=args.knowledge_dir,
        index_path=args.index_path,
        backend=args.backend,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        max_features=args.max_features,
        embedding_model=args.embedding_model,
        embedding_batch_size=args.embedding_batch_size,
    )

    print(f"Indice guardado en: {result.index_path}")
    print(f"Backend de indice: {result.backend}")
    print(f"Empresas indexadas: {', '.join(result.companies)}")
    print(f"Documentos procesados: {result.total_documents}")
    print(f"Chunks generados: {result.total_chunks}")


if __name__ == "__main__":
    main()
