from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
from datetime import datetime

from clasificacion_langchain.agents.document_storage import LocalDocumentStorage, build_document_storage_from_env
from clasificacion_langchain.agents.repository import AgentDocumentRecord, AgentRecord
from clasificacion_langchain.agents.sqlite_repository import SQLiteAgentRepository


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migra documentos locales de agentes")
    parser.add_argument("--db-path", default=os.getenv("SQLITE_DB_PATH", "backend/data/local_api.db"))
    parser.add_argument("--knowledge-root", default=os.getenv("AGENTS_KNOWLEDGE_ROOT", "backend/knowledge_base/agents"))
    parser.add_argument("--backend", choices=["local", "s3"], default=os.getenv("DOC_STORAGE_BACKEND", "local"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delete-source", action="store_true")
    return parser.parse_args()


def _build_agent(row: sqlite3.Row) -> AgentRecord:
    return AgentRecord(
        agent_id=row["agent_id"], org_id=row["org_id"], company_id=row["company_id"], name=row["name"],
        objective=row["objective"], tone=row["tone"], description=row["description"], rag_backend=row["rag_backend"],
        generation_provider=row["generation_provider"], use_openai_generation=bool(row["use_openai_generation"]),
        openai_model=row["openai_model"], knowledge_dir=row["knowledge_dir"], index_path=row["index_path"],
        created_at=datetime.fromisoformat(row["agent_created_at"]), updated_at=datetime.fromisoformat(row["agent_updated_at"]),
        indexed_at=_parse_datetime(row["agent_indexed_at"]),
    )


def _build_document(row: sqlite3.Row) -> AgentDocumentRecord:
    return AgentDocumentRecord(
        document_id=row["document_id"], agent_id=row["agent_id"], filename=row["filename"], stored_path=row["stored_path"],
        storage_provider=row["storage_provider"] or "local", storage_key=row["storage_key"] or row["stored_path"],
        content_type=row["content_type"], checksum_sha256=row["checksum_sha256"], size_bytes=int(row["size_bytes"]),
        status=row["status"], indexed_at=_parse_datetime(row["indexed_at"]), error_message=row["error_message"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def main() -> None:
    args = parse_args()
    SQLiteAgentRepository(args.db_path)
    os.environ["DOC_STORAGE_BACKEND"] = args.backend
    target_storage = build_document_storage_from_env(knowledge_root=args.knowledge_root)
    source_storage = LocalDocumentStorage(knowledge_root=args.knowledge_root)
    with sqlite3.connect(args.db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT d.*, a.org_id, a.company_id, a.name, a.objective, a.tone, a.description, a.rag_backend,
                   a.generation_provider, a.use_openai_generation, a.openai_model, a.knowledge_dir, a.index_path,
                   a.created_at AS agent_created_at, a.updated_at AS agent_updated_at, a.indexed_at AS agent_indexed_at
            FROM agent_documents d INNER JOIN agents a ON a.agent_id = d.agent_id ORDER BY d.created_at ASC
            """
        ).fetchall()
        migrated = skipped = failed = 0
        for row in rows:
            agent = _build_agent(row)
            document = _build_document(row)
            if document.storage_provider == args.backend and document.storage_key:
                skipped += 1
                continue
            if document.storage_provider != "local":
                skipped += 1
                continue
            try:
                content = source_storage.read(document)
                content_type = document.content_type or "application/octet-stream"
                target = target_storage.save(agent=agent, filename=document.filename, content=content, content_type=content_type)
                checksum = hashlib.sha256(content).hexdigest()
                if not args.dry_run:
                    conn.execute(
                        """
                        UPDATE agent_documents SET storage_provider = ?, storage_key = ?, stored_path = ?, content_type = ?, checksum_sha256 = ?
                        WHERE document_id = ?
                        """,
                        (target.provider, target.key, target.key, content_type, checksum, document.document_id),
                    )
                if args.delete_source and args.backend != "local" and not args.dry_run:
                    source_storage.delete(document)
                migrated += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"[ERROR] document_id={document.document_id} filename={document.filename} detail={exc}")
        if not args.dry_run:
            conn.commit()
    print(f"Backend destino: {args.backend}")
    print(f"Migrados: {migrated}")
    print(f"Omitidos: {skipped}")
    print(f"Fallidos: {failed}")
    if args.dry_run:
        print("Dry-run activo: no se actualizaron registros")


if __name__ == "__main__":
    main()
