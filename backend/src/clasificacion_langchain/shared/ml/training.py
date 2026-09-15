from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import LinearSVC

from clasificacion_langchain.shared.ml.text_cleaning import normalize_text


@dataclass
class TrainingResult:
    model_path: Path
    accuracy: float
    report: str
    labels: list[str]


def _build_pipeline(max_features: int = 5000) -> Pipeline:
    return Pipeline(steps=[("tfidf", TfidfVectorizer(max_features=max_features, ngram_range=(1, 2))), ("clf", LinearSVC(C=1.0))])


def train_classifier(df: pd.DataFrame, model_path: str = "models/classifier.joblib", test_size: float = 0.3, random_state: int = 500) -> TrainingResult:
    data = df.copy()
    data["text"] = data["text"].astype(str).apply(normalize_text)
    data = data[data["text"].str.len() > 0]
    x_train, x_test, y_train, y_test = train_test_split(
        data["text"], data["label"], test_size=test_size, random_state=random_state, stratify=data["label"]
    )
    encoder = LabelEncoder()
    y_train_encoded = encoder.fit_transform(y_train)
    y_test_encoded = encoder.transform(y_test)
    pipeline = _build_pipeline()
    pipeline.fit(x_train, y_train_encoded)
    predictions = pipeline.predict(x_test)
    accuracy = accuracy_score(y_test_encoded, predictions)
    report = classification_report(y_test_encoded, predictions, target_names=encoder.classes_, zero_division=0)
    model_file = Path(model_path)
    model_file.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipeline, "label_encoder": encoder, "metrics": {"accuracy": accuracy, "report": report}}, model_file)
    return TrainingResult(model_path=model_file, accuracy=accuracy, report=report, labels=list(encoder.classes_))
