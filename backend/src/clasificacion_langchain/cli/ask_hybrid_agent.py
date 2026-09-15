from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from clasificacion_langchain.rag.pipeline import RAGPipeline
from clasificacion_langchain.shared.ml.agent_tools import AgentToolset
from clasificacion_langchain.shared.ml.hybrid_agent_graph import build_hybrid_agent_graph
from clasificacion_langchain.shared.ml.intent_router import IntentRouter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consulta agente hibrido")
    parser.add_argument("--question", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--index-path", default="backend/models/rag_index.joblib")
    parser.add_argument("--intent-model-path", default="backend/models/intent_router.joblib")
    parser.add_argument("--use-openai", action="store_true")
    parser.add_argument("--confidence-threshold", type=float, default=0.45)
    parser.add_argument("--top-k", type=int, default=4)
    return parser.parse_args()


def _maybe_load_router(model_path: str) -> IntentRouter | None:
    path = Path(model_path)
    if not path.exists():
        return None
    return IntentRouter(model_path=str(path))


def main() -> None:
    load_dotenv()
    args = parse_args()
    rag_pipeline = RAGPipeline.from_artifact(index_path=args.index_path, use_openai=args.use_openai)
    intent_router = _maybe_load_router(args.intent_model_path)
    graph = build_hybrid_agent_graph(
        toolset=AgentToolset(rag_pipeline=rag_pipeline, intent_router=intent_router),
        confidence_threshold=args.confidence_threshold,
    )
    result = graph.invoke({"raw_text": args.question, "company_id": args.company_id, "top_k": args.top_k})
    print(f"Route: {result.get('route', 'unknown')} ({result.get('route_reason', 'n/a')})")
    print(f"Intent: {result.get('intent_label', 'n/a')} ({float(result.get('intent_confidence', 0.0)):.2f})")
    print(f"Respuesta:\n{result.get('final_answer', '')}")
    sources = result.get("sources", [])
    if sources:
        print("\nFuentes:")
        for source in sources:
            print(f"- {source}")


if __name__ == "__main__":
    main()
