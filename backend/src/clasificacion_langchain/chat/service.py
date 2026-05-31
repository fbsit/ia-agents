from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from clasificacion_langchain.agent_tools import AgentToolset
from clasificacion_langchain.chat.config import ChatServiceConfig
from clasificacion_langchain.chat.memory_store import InMemorySessionStore
from clasificacion_langchain.chat.session_store import SessionStore
from clasificacion_langchain.chat.schemas import ChatRequest, ChatResponse
from clasificacion_langchain.hybrid_agent_graph import build_hybrid_agent_graph
from clasificacion_langchain.intent_router import IntentRouter
from clasificacion_langchain.rag.pipeline import RAGPipeline


def _format_history_for_query(history: list[tuple[str, str]]) -> str:
    if not history:
        return ""

    lines = ["Contexto breve de conversacion previa:"]
    for role, text in history:
        role_name = "Usuario" if role == "user" else "Asistente"
        lines.append(f"- {role_name}: {text}")
    return "\n".join(lines)


class ChatService:
    def __init__(
        self,
        config: ChatServiceConfig,
        session_store: SessionStore | None = None,
    ) -> None:
        self.config = config
        self.memory = session_store or InMemorySessionStore(
            max_turns=config.max_session_turns
        )

        rag_pipeline = RAGPipeline.from_artifact(
            index_path=config.rag_index_path,
            use_openai=config.use_openai,
            openai_model=config.openai_model,
            generation_provider=config.generation_provider,
            anthropic_model=config.anthropic_model,
        )
        intent_router = self._load_router_if_available(config.intent_model_path)
        toolset = AgentToolset(rag_pipeline=rag_pipeline, intent_router=intent_router)

        self.graph = build_hybrid_agent_graph(
            toolset=toolset,
            rag_intents=config.rag_intents,
            confidence_threshold=config.confidence_threshold,
        )

    def _load_router_if_available(self, model_path: str) -> IntentRouter | None:
        path = Path(model_path)
        if not path.exists():
            return None
        return IntentRouter(model_path=str(path))

    def _session_history(self, company_id: str, session_id: str) -> list[tuple[str, str]]:
        turns = self.memory.recent_turns(company_id, session_id, limit=4)
        return [(turn.role, turn.text) for turn in turns]

    def _build_query(self, message: str, history: list[tuple[str, str]]) -> str:
        history_block = _format_history_for_query(history)
        if not history_block:
            return message
        return f"{history_block}\n\nConsulta actual: {message}"

    def chat(self, request: ChatRequest) -> ChatResponse:
        if not request.company_id.strip():
            raise ValueError("company_id es requerido para preservar aislamiento tenant")
        if not request.session_id.strip():
            raise ValueError("session_id es requerido")

        trace_id = uuid4().hex[:12]
        history = self._session_history(request.company_id, request.session_id)
        query = self._build_query(request.message, history)

        graph_result = self.graph.invoke(
            {
                "raw_text": request.message,
                "rag_query": query,
                "company_id": request.company_id,
                "top_k": request.top_k,
                "generation_provider": request.generation_provider,
                "generation_model": request.generation_model,
                "use_openai_generation": request.use_openai_generation,
            }
        )

        answer = str(graph_result.get("final_answer", ""))
        sources = list(graph_result.get("sources", []))
        route = str(graph_result.get("route", "fallback"))
        route_reason = str(graph_result.get("route_reason", "unspecified"))
        intent_label = str(graph_result.get("intent_label", "sin_router"))
        intent_confidence = float(graph_result.get("intent_confidence", 1.0))

        escalation_required = route == "fallback" or (route == "rag" and not sources)
        if route == "rag" and not sources:
            route_reason = "empty_retrieval_context"

        self.memory.append_user_message(
            company_id=request.company_id,
            session_id=request.session_id,
            text=request.message,
        )
        self.memory.append_assistant_message(
            company_id=request.company_id,
            session_id=request.session_id,
            text=answer,
        )

        return ChatResponse(
            trace_id=trace_id,
            company_id=request.company_id,
            session_id=request.session_id,
            answer=answer,
            route=route,
            route_reason=route_reason,
            intent_label=intent_label,
            intent_confidence=intent_confidence,
            sources=sources,
            escalation_required=escalation_required,
        )
