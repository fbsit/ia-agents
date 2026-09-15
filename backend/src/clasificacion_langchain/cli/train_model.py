from __future__ import annotations

import argparse

from clasificacion_langchain.shared.ml.data_sources import (
    load_csv_dataset,
    load_mysql_dataset,
    mysql_config_from_env,
)
from clasificacion_langchain.shared.ml.training import train_classifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entrena clasificador de texto")
    parser.add_argument("--task", choices=["sentiment", "intent"], default="sentiment")
    parser.add_argument("--source", choices=["csv", "mysql"], default="csv")
    parser.add_argument("--csv-path", default="backend/data/sample_tweets.csv")
    parser.add_argument("--model-path", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_path = args.model_path or (
        "backend/models/intent_router.joblib" if args.task == "intent" else "backend/models/classifier.joblib"
    )
    dataset = load_mysql_dataset(mysql_config_from_env()) if args.source == "mysql" else load_csv_dataset(args.csv_path)
    result = train_classifier(dataset, model_path=model_path)
    print(f"Modelo guardado en: {result.model_path}")
    print(f"Accuracy: {result.accuracy:.4f}")
    print("Reporte:\n")
    print(result.report)


if __name__ == "__main__":
    main()
