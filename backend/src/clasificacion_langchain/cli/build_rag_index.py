from __future__ import annotations

import argparse

from clasificacion_langchain.rag.pipeline import build_and_save_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Construye indice RAG multiempresa")
    parser.add_argument("--knowledge-dir", default="backend/knowledge_base")
    parser.add_argument("--index-path", default="backend/models/rag_index.joblib")
    parser.add_argument("--backend", choices=["auto", "tfidf", "dense_openai", "hybrid"], default="auto")
    parser.add_argument("--chunk-size", type=int, default=900)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    parser.add_argument("--max-features", type=int, default=20000)
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--embedding-batch-size", type=int, default=64)
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
