from __future__ import annotations

from typing import TypedDict

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from clasificacion_langchain.agent_tools import AgentToolset
from clasificacion_langchain.text_cleaning import normalize_text


class HybridAgentState(TypedDict, total=False):
    raw_text: str
    rag_query: str
    company_id: str
    top_k: int
    generation_provider: str | None
    generation_model: str | None
    use_openai_generation: bool | None
    cleaned_text: str
    intent_label: str
    intent_confidence: float
    route: str
    route_reason: str
    final_answer: str
    sources: list[str]


def build_hybrid_agent_graph(
    toolset: AgentToolset,
    rag_intents: set[str] | None = None,
    confidence_threshold: float = 0.45,
):
    active_rag_intents = rag_intents or set()

    def normalize_node(state: HybridAgentState) -> HybridAgentState:
        cleaned = normalize_text(state.get("raw_text", ""))
        return {"cleaned_text": cleaned}

    def route_node(state: HybridAgentState) -> HybridAgentState:
        prediction = toolset.classify_intent(state.get("cleaned_text", ""))
        label = str(prediction.get("label", "sin_router"))
        confidence = float(prediction.get("confidence", 0.0))

        should_use_rag = True
        route_reason = "intent_confident"

        if toolset.intent_router is not None:
            if active_rag_intents:
                should_use_rag = (
                    label in active_rag_intents and confidence >= confidence_threshold
                )
            else:
                should_use_rag = confidence >= confidence_threshold
            if not should_use_rag:
                route_reason = "low_intent_confidence"
        else:
            route_reason = "no_intent_router"

        return {
            "intent_label": label,
            "intent_confidence": confidence,
            "route": "rag" if should_use_rag else "fallback",
            "route_reason": route_reason,
        }

    def rag_node(state: HybridAgentState) -> HybridAgentState:
        top_k = int(state.get("top_k", 4))
        rag_query = state.get("rag_query", state.get("raw_text", ""))
        answer = toolset.answer_company_question(
            query=rag_query,
            company_id=state.get("company_id", ""),
            top_k=top_k,
            generation_provider=state.get("generation_provider"),
            generation_model=state.get("generation_model"),
            use_openai_generation=state.get("use_openai_generation"),
        )
        return {
            "final_answer": answer.answer,
            "sources": answer.sources,
        }

    def fallback_node(state: HybridAgentState) -> HybridAgentState:
        return {
            "final_answer": (
                "No tengo suficiente confianza para responder automaticamente. "
                "Te recomiendo pedir una aclaracion o derivar a un humano."
            ),
            "sources": [],
        }

    def route_selector(state: HybridAgentState) -> str:
        route = state.get("route", "fallback")
        return "rag" if route == "rag" else "fallback"

    graph = StateGraph(HybridAgentState)
    graph.add_node("normalize", RunnableLambda(normalize_node))
    graph.add_node("route", RunnableLambda(route_node))
    graph.add_node("rag", RunnableLambda(rag_node))
    graph.add_node("fallback", RunnableLambda(fallback_node))

    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "route")
    graph.add_conditional_edges(
        "route",
        route_selector,
        {
            "rag": "rag",
            "fallback": "fallback",
        },
    )
    graph.add_edge("rag", END)
    graph.add_edge("fallback", END)

    return graph.compile()
