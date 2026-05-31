from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from clasificacion_langchain.rag.generation import (  # noqa: E402
    ExtractiveAnswerGenerator,
    tune_answer_style,
)
from clasificacion_langchain.rag.schemas import RetrievedChunk  # noqa: E402


def test_tune_answer_style_removes_numbering_and_references() -> None:
    raw_answer = (
        "1) El plazo de devolucion es de 30 dias corridos.\n"
        "2) Que aprendemos\n"
        "- Debes respetar el plazo.\n"
        "3) Referencias usadas: [1]\n"
        "Fuentes: facts-canonicos.md"
    )

    tuned = tune_answer_style(raw_answer)

    assert "1)" not in tuned
    assert "Referencias usadas" not in tuned
    assert "Fuentes:" not in tuned
    assert "30 dias" in tuned


def test_tune_answer_style_removes_inline_numbered_format() -> None:
    raw_answer = (
        "1) El plazo para realizar una devolucion es de 30 dias corridos a partir de la fecha de compra. "
        "2) - Las devoluciones deben gestionarse dentro de un periodo especifico para garantizar la satisfaccion del cliente. "
        "- Es importante que los empleados conozcan las politicas de devoluciones para brindar un servicio adecuado. "
        "3) Referencias usadas: [1]."
    )

    tuned = tune_answer_style(raw_answer)

    assert "1)" not in tuned
    assert "2)" not in tuned
    assert "3)" not in tuned
    assert "Referencias usadas" not in tuned
    assert "30 dias" in tuned


def test_tune_answer_style_factoid_keeps_only_direct_sentence() -> None:
    raw_answer = (
        "El plazo para realizar una devolucion es de 30 dias corridos a partir de la fecha de compra. "
        "Las devoluciones deben gestionarse dentro de un plazo especifico para ser aceptadas. "
        "Es importante conocer las politicas internas para evitar inconvenientes."
    )

    tuned = tune_answer_style(raw_answer, query="cuantos dias son para una devolucion?")

    assert tuned == "El plazo para realizar una devolucion es de 30 dias corridos a partir de la fecha de compra."


def test_extractive_generator_returns_natural_response_without_sources_line() -> None:
    generator = ExtractiveAnswerGenerator(openai_requested=False, openai_available=False)
    chunks = [
        RetrievedChunk(
            chunk_id="a1",
            company_id="kronix",
            source="facts-canonicos.md",
            text="El plazo para la devolucion es de 30 dias corridos desde la fecha de compra.",
            score=0.78,
            position=0,
        ),
        RetrievedChunk(
            chunk_id="a2",
            company_id="kronix",
            source="rules-decision-table.md",
            text="Si el monto supera el limite de autorizacion, la solicitud se escala a revision manual.",
            score=0.63,
            position=1,
        ),
    ]

    answer = generator.generate(
        query="Cual es el plazo de devolucion?",
        chunks=chunks,
        objective="Resolver dudas operativas",
        tone="profesional",
    )

    assert "Fuentes:" not in answer
    assert "Referencias" not in answer
    assert "Respuesta directa:" not in answer
    assert "Objetivo del agente aplicado:" not in answer
    assert "30 dias" in answer
