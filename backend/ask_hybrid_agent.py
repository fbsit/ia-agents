from __future__ import annotations

import argparse
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.agent_tools import AgentToolset
from clasificacion_langchain.hybrid_agent_graph import build_hybrid_agent_graph
from clasificacion_langchain.intent_router import IntentRouter
from clasificacion_langchain.rag.pipeline import RAGPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consulta agente hibrido (intent + RAG)")
    parser.add_argument("--question", required=True, help="Pregunta del usuario")
    parser.add_argument("--company-id", required=True, help="Empresa objetivo")
    parser.add_argument(
        "--index-path",
        default="models/rag_index.joblib",
        help="Ruta del indice RAG",
    )
    parser.add_argument(
        "--intent-model-path",
        default="models/intent_router.joblib",
        help="Ruta del modelo de intenciones",
    )
    parser.add_argument(
        "--use-openai",
        action="store_true",
        help="Usa OpenAI para generar respuesta final",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.45,
        help="Umbral minimo de confianza del router",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=4,
        help="Cantidad de chunks a recuperar",
    )
    return parser.parse_args()


def _maybe_load_router(model_path: str) -> IntentRouter | None:
    path = Path(model_path)
    if not path.exists():
        return None
    return IntentRouter(model_path=str(path))


def main() -> None:
    load_dotenv()
    args = parse_args()
    rag_pipeline = RAGPipeline.from_artifact(
        index_path=args.index_path,
        use_openai=args.use_openai,
    )
    intent_router = _maybe_load_router(args.intent_model_path)
    toolset = AgentToolset(rag_pipeline=rag_pipeline, intent_router=intent_router)

    graph = build_hybrid_agent_graph(
        toolset=toolset,
        confidence_threshold=args.confidence_threshold,
    )
    result = graph.invoke(
        {
            "raw_text": args.question,
            "company_id": args.company_id,
            "top_k": args.top_k,
        }
    )

    print(f"Route: {result.get('route', 'unknown')} ({result.get('route_reason', 'n/a')})")
    print(
        "Intent: "
        f"{result.get('intent_label', 'n/a')} "
        f"({float(result.get('intent_confidence', 0.0)):.2f})"
    )
    print(f"Respuesta:\n{result.get('final_answer', '')}")
    sources = result.get("sources", [])
    if sources:
        print("\nFuentes:")
        for source in sources:
            print(f"- {source}")


if __name__ == "__main__":
    main()
