from __future__ import annotations

import hashlib
import re
from pathlib import Path

from clasificacion_langchain.rag.schemas import ChunkedDocument, KnowledgeDocument


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    clean_text = " ".join(text.split())
    if not clean_text:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size debe ser mayor a 0")

    if overlap < 0:
        raise ValueError("overlap no puede ser negativo")

    step = max(chunk_size - overlap, 1)
    chunks: list[str] = []

    start = 0
    while start < len(clean_text):
        end = min(start + chunk_size, len(clean_text))
        chunk = clean_text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(clean_text):
            break
        start += step

    return chunks


def _split_markdown_sections(text: str) -> list[str]:
    lines = text.splitlines()
    sections: list[str] = []
    current_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if line.lstrip().startswith("#") and current_lines:
            section = "\n".join(current_lines).strip()
            if section:
                sections.append(section)
            current_lines = [line]
            continue
        current_lines.append(line)

    if current_lines:
        section = "\n".join(current_lines).strip()
        if section:
            sections.append(section)

    return sections


def _chunk_markdown_semantic(text: str, chunk_size: int, overlap: int) -> list[str]:
    sections = _split_markdown_sections(text)
    if not sections:
        return _chunk_text(text, chunk_size=chunk_size, overlap=overlap)

    chunks: list[str] = []
    for section in sections:
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", section)
            if paragraph.strip()
        ]
        if not paragraphs:
            continue

        buffer = ""
        for paragraph in paragraphs:
            candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
            if len(candidate) <= chunk_size:
                buffer = candidate
                continue

            if buffer:
                chunks.append(buffer)

            if len(paragraph) <= chunk_size:
                buffer = paragraph
                continue

            oversized_chunks = _chunk_text(paragraph, chunk_size=chunk_size, overlap=overlap)
            if not oversized_chunks:
                buffer = ""
                continue

            chunks.extend(oversized_chunks[:-1])
            buffer = oversized_chunks[-1]

        if buffer:
            chunks.append(buffer)

    if not chunks:
        return _chunk_text(text, chunk_size=chunk_size, overlap=overlap)

    return chunks


def _chunk_rows(text: str, chunk_size: int, max_rows: int) -> list[str]:
    """
    Datos tabulares (CSV/JSON por linea): una fila es la unidad minima de sentido.
    Se agrupan filas consecutivas hasta `chunk_size` caracteres o `max_rows` filas,
    sin partir nunca una fila. Si el origen viene ordenado por categoria, cada chunk
    queda tematicamente coherente (todos los cafes juntos, etc.).
    """
    rows = [line.strip() for line in text.splitlines() if line.strip()]
    if not rows:
        return []
    chunks: list[str] = []
    buffer: list[str] = []
    size = 0
    for row in rows:
        row_len = len(row) + 1
        if buffer and (size + row_len > chunk_size or len(buffer) >= max_rows):
            chunks.append("\n".join(buffer))
            buffer, size = [], 0
        buffer.append(row)
        size += row_len
    if buffer:
        chunks.append("\n".join(buffer))
    return chunks


def chunk_documents(
    documents: list[KnowledgeDocument],
    chunk_size: int = 900,
    overlap: int = 120,
    min_length: int = 50,
    table_chunk_size: int = 600,
    table_max_rows: int = 6,
) -> list[ChunkedDocument]:
    chunks: list[ChunkedDocument] = []

    for document in documents:
        extension = document.metadata.get("extension", "").strip().lower()
        if not extension:
            extension = Path(document.source).suffix.lower()

        if extension == ".md":
            raw_chunks = _chunk_markdown_semantic(
                document.text,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        elif extension in {".csv", ".json"}:
            raw_chunks = _chunk_rows(document.text, chunk_size=table_chunk_size, max_rows=table_max_rows)
        else:
            raw_chunks = _chunk_text(document.text, chunk_size=chunk_size, overlap=overlap)

        # min_length descarta fragmentos residuales, pero nunca debe vaciar un
        # documento entero: si todos sus chunks son cortos se conserva el primero.
        selected = [(position, chunk) for position, chunk in enumerate(raw_chunks) if len(chunk) >= min_length]
        if not selected and raw_chunks:
            selected = [(0, raw_chunks[0])]

        for position, chunk in selected:
            digest = hashlib.sha1(
                f"{document.company_id}|{document.source}|{position}|{chunk}".encode(
                    "utf-8"
                )
            ).hexdigest()
            chunk_id = digest[:16]

            chunks.append(
                ChunkedDocument(
                    chunk_id=chunk_id,
                    company_id=document.company_id,
                    source=document.source,
                    text=chunk,
                    position=position,
                    metadata=document.metadata.copy(),
                )
            )

    if not chunks:
        raise ValueError("No se pudieron generar chunks validos")

    return chunks
