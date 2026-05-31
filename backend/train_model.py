from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.data_sources import (
    load_csv_dataset,
    load_mysql_dataset,
    mysql_config_from_env,
)
from clasificacion_langchain.training import train_classifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entrena clasificador de texto")
    parser.add_argument(
        "--task",
        choices=["sentiment", "intent"],
        default="sentiment",
        help="Tipo de modelo a entrenar",
    )
    parser.add_argument(
        "--source",
        choices=["csv", "mysql"],
        default="csv",
        help="Fuente de datos",
    )
    parser.add_argument(
        "--csv-path",
        default="data/sample_tweets.csv",
        help="Ruta CSV (si source=csv)",
    )
    parser.add_argument(
        "--model-path",
        default="",
        help="Ruta de salida del modelo (opcional)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_path = args.model_path or (
        "models/intent_router.joblib"
        if args.task == "intent"
        else "models/classifier.joblib"
    )

    if args.source == "mysql":
        config = mysql_config_from_env()
        dataset = load_mysql_dataset(config)
    else:
        dataset = load_csv_dataset(args.csv_path)

    result = train_classifier(dataset, model_path=model_path)

    print(f"Modelo guardado en: {result.model_path}")
    print(f"Accuracy: {result.accuracy:.4f}")
    print("Reporte:\n")
    print(result.report)


if __name__ == "__main__":
    main()
