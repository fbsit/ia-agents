from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from clasificacion_langchain.rag.index_loader import load_index  # noqa: E402
from clasificacion_langchain.rag.pipeline import build_and_save_index  # noqa: E402


def test_knowledge_structure_and_index_keep_tenant_isolation(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "knowledge_base"
    (knowledge_root / "empresa_a").mkdir(parents=True)
    (knowledge_root / "empresa_b").mkdir(parents=True)

    (knowledge_root / "empresa_a" / "facts-canonicos.md").write_text(
        "Horario de soporte empresa_a: lunes a viernes 9 a 18.",
        encoding="utf-8",
    )
    (knowledge_root / "empresa_b" / "facts-canonicos.md").write_text(
        "Horario de soporte empresa_b: sabado de 10 a 14.",
        encoding="utf-8",
    )

    index_path = tmp_path / "models" / "rag_index.joblib"
    result = build_and_save_index(
        knowledge_dir=knowledge_root,
        index_path=index_path,
        backend="tfidf",
    )

    assert result.backend == "tfidf"
    assert result.companies == ["empresa_a", "empresa_b"]
    assert result.total_documents == 2
    assert result.total_chunks >= 2

    index = load_index(index_path)
    hits_a = index.search(query="horario soporte", company_id="empresa_a", top_k=3)
    hits_b = index.search(query="horario soporte", company_id="empresa_b", top_k=3)

    assert hits_a
    assert hits_b
    assert all(hit.company_id == "empresa_a" for hit in hits_a)
    assert all(hit.company_id == "empresa_b" for hit in hits_b)
    assert all(hit.source.startswith("empresa_a/") for hit in hits_a)
    assert all(hit.source.startswith("empresa_b/") for hit in hits_b)
