from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

import joblib
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from clasificacion_langchain.ml_utils import build_scores_from_decision
from clasificacion_langchain.text_cleaning import normalize_text


class InferenceState(TypedDict, total=False):
    raw_text: str
    cleaned_text: str
    label: str
    confidence: float
    scores: dict[str, float]
    explanation: str


def _build_scores(labels: list[str], decision_values: Any) -> tuple[str, float, dict[str, float]]:
    return build_scores_from_decision(labels, decision_values)


def build_inference_graph(model_path: str = "models/classifier.joblib"):
    artifact = joblib.load(Path(model_path))
    pipeline = artifact["pipeline"]
    label_encoder = artifact["label_encoder"]
    labels = list(label_encoder.classes_)

    def normalize_node(state: InferenceState) -> InferenceState:
        cleaned = normalize_text(state["raw_text"])
        return {"cleaned_text": cleaned}

    def classify_node(state: InferenceState) -> InferenceState:
        cleaned_text = state.get("cleaned_text", "")
        encoded_pred = int(pipeline.predict([cleaned_text])[0])
        decision = pipeline.decision_function([cleaned_text])[0]
        predicted_label, confidence, scores = _build_scores(labels, decision)

        if predicted_label != labels[encoded_pred]:
            predicted_label = labels[encoded_pred]
            confidence = scores.get(predicted_label, confidence)

        return {
            "label": predicted_label,
            "confidence": confidence,
            "scores": scores,
        }

    prompt = PromptTemplate.from_template(
        "Prediccion: {label}\n"
        "Confianza estimada: {confidence:.2%}\n"
        "Texto normalizado: {cleaned_text}\n"
        "Top scores: {scores}"
    )

    def explain_node(state: InferenceState) -> InferenceState:
        explanation = prompt.format(
            label=state.get("label", "desconocido"),
            confidence=state.get("confidence", 0.0),
            cleaned_text=state.get("cleaned_text", ""),
            scores=state.get("scores", {}),
        )
        return {"explanation": explanation}

    graph = StateGraph(InferenceState)
    graph.add_node("normalize", RunnableLambda(normalize_node))
    graph.add_node("classify", RunnableLambda(classify_node))
    graph.add_node("explain", RunnableLambda(explain_node))

    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "classify")
    graph.add_edge("classify", "explain")
    graph.add_edge("explain", END)

    return graph.compile()
