from __future__ import annotations

from typing import Any

import numpy as np


def softmax(values: np.ndarray) -> np.ndarray:
    exp_values = np.exp(values - np.max(values))
    return exp_values / exp_values.sum()


def build_scores_from_decision(labels: list[str], decision_values: Any) -> tuple[str, float, dict[str, float]]:
    values = np.array(decision_values)
    if values.ndim == 0:
        values = np.array([float(values)])
    if values.ndim == 1 and values.shape[0] == 1 and len(labels) == 2:
        values = np.array([-values[0], values[0]])
    probabilities = softmax(values)
    if len(probabilities) != len(labels):
        probabilities = np.ones(len(labels), dtype=float) / float(len(labels))
    best_idx = int(np.argmax(probabilities))
    scores = {label: float(probability) for label, probability in zip(labels, probabilities)}
    return labels[best_idx], float(probabilities[best_idx]), scores
