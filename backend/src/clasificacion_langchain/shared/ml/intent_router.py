from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from clasificacion_langchain.shared.ml.ml_utils import build_scores_from_decision
from clasificacion_langchain.shared.ml.text_cleaning import normalize_text


@dataclass
class IntentPrediction:
    label: str
    confidence: float
    scores: dict[str, float]


class IntentRouter:
    def __init__(self, model_path: str = "models/intent_router.joblib") -> None:
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"No existe modelo de intent router en {path}. Entrena uno y vuelve a intentar.")
        artifact = joblib.load(path)
        self.pipeline = artifact["pipeline"]
        self.label_encoder = artifact["label_encoder"]
        self.labels = list(self.label_encoder.classes_)

    def _decision_values(self, clean_text: str) -> Any:
        if hasattr(self.pipeline, "decision_function"):
            return self.pipeline.decision_function([clean_text])[0]
        if hasattr(self.pipeline, "predict_proba"):
            return self.pipeline.predict_proba([clean_text])[0]
        raise ValueError("El modelo no expone decision_function ni predict_proba para estimar confianza.")

    def predict(self, text: str) -> IntentPrediction:
        clean_text = normalize_text(text or "")
        if not clean_text:
            return IntentPrediction(label="desconocido", confidence=0.0, scores={})
        predicted_index = int(self.pipeline.predict([clean_text])[0])
        predicted_label = self.labels[predicted_index]
        decision_values = self._decision_values(clean_text)
        score_label, confidence, scores = build_scores_from_decision(self.labels, decision_values)
        if score_label != predicted_label:
            confidence = scores.get(predicted_label, confidence)
        return IntentPrediction(label=predicted_label, confidence=confidence, scores=scores)
