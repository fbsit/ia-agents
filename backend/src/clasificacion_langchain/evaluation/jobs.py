from __future__ import annotations

from clasificacion_langchain.persistence.pg_connections import pooled_connection

import json
import logging
import os
import queue as stdlib_queue
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class EvaluationJobStore:
    def create(self, row: dict[str, Any]) -> None:
        raise NotImplementedError

    def get(self, job_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        run: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        raise NotImplementedError


class InMemoryEvaluationJobStore(EvaluationJobStore):
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._rows[str(row.get("job_id"))] = dict(row)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(job_id)
            return dict(row) if row is not None else None

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        run: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(job_id)
            if row is None:
                return None
            if status is not None:
                row["status"] = status
            row["error"] = error
            if run is not None:
                row["run"] = run
            row["updated_at"] = _now_iso()
            self._rows[job_id] = row
            return dict(row)


class SQLiteEvaluationJobStore(EvaluationJobStore):
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_jobs (
                    job_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sample_size INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT,
                    run_json TEXT
                )
                """
            )

    def create(self, row: dict[str, Any]) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO evaluation_jobs
                    (job_id, agent_id, company_id, status, sample_size, created_at, updated_at, error, run_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("job_id"),
                        row.get("agent_id"),
                        row.get("company_id"),
                        row.get("status"),
                        row.get("sample_size"),
                        row.get("created_at"),
                        row.get("updated_at"),
                        row.get("error"),
                        json.dumps(row.get("run"), ensure_ascii=True) if row.get("run") is not None else None,
                    ),
                )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT job_id, agent_id, company_id, status, sample_size, created_at, updated_at, error, run_json
                FROM evaluation_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            run_json = row[8]
            run_payload = json.loads(run_json) if run_json else None
            return {
                "job_id": row[0],
                "agent_id": row[1],
                "company_id": row[2],
                "status": row[3],
                "sample_size": row[4],
                "created_at": row[5],
                "updated_at": row[6],
                "error": row[7],
                "run": run_payload,
            }

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        run: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            current = self.get(job_id)
            if current is None:
                return None
            next_row = dict(current)
            if status is not None:
                next_row["status"] = status
            next_row["error"] = error
            if run is not None:
                next_row["run"] = run
            next_row["updated_at"] = _now_iso()
            self.create(next_row)
            return next_row


class PostgresEvaluationJobStore(EvaluationJobStore):
    def __init__(self, dsn: str, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = schema
        self._lock = threading.Lock()
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError("psycopg no esta instalado para EVAL_JOB_STORAGE_BACKEND=postgres") from exc
        self._psycopg = psycopg
        self._ensure_schema()

    def _connect(self):
        return pooled_connection(self._psycopg, self.dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.schema}.evaluation_jobs (
                        job_id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        company_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        sample_size INTEGER,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        error TEXT,
                        run_json JSONB
                    )
                    """
                )

    def create(self, row: dict[str, Any]) -> None:
        with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self.schema}.evaluation_jobs
                        (job_id, agent_id, company_id, status, sample_size, created_at, updated_at, error, run_json)
                        VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz, %s, %s::jsonb)
                        ON CONFLICT (job_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            sample_size = EXCLUDED.sample_size,
                            updated_at = EXCLUDED.updated_at,
                            error = EXCLUDED.error,
                            run_json = EXCLUDED.run_json
                        """,
                        (
                            row.get("job_id"),
                            row.get("agent_id"),
                            row.get("company_id"),
                            row.get("status"),
                            row.get("sample_size"),
                            row.get("created_at"),
                            row.get("updated_at"),
                            row.get("error"),
                            json.dumps(row.get("run"), ensure_ascii=True) if row.get("run") is not None else None,
                        ),
                    )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT job_id, agent_id, company_id, status, sample_size,
                           created_at::text, updated_at::text, error, run_json
                    FROM {self.schema}.evaluation_jobs
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {
                    "job_id": row[0],
                    "agent_id": row[1],
                    "company_id": row[2],
                    "status": row[3],
                    "sample_size": row[4],
                    "created_at": row[5],
                    "updated_at": row[6],
                    "error": row[7],
                    "run": row[8],
                }

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        run: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            current = self.get(job_id)
            if current is None:
                return None
            next_row = dict(current)
            if status is not None:
                next_row["status"] = status
            next_row["error"] = error
            if run is not None:
                next_row["run"] = run
            next_row["updated_at"] = _now_iso()
            self.create(next_row)
            return next_row


def build_evaluation_job_store_from_env(
    *,
    persistence_backend: str = "sqlite",
    sqlite_db_path: str | None = None,
) -> EvaluationJobStore:
    configured = os.getenv("EVAL_JOB_STORAGE_BACKEND", "auto").strip().lower()
    if configured == "auto":
        configured = "sqlite" if persistence_backend == "sqlite" else "memory"

    if configured == "postgres":
        dsn = os.getenv("EVAL_JOB_POSTGRES_DSN", "").strip()
        schema = os.getenv("EVAL_JOB_POSTGRES_SCHEMA", "public").strip() or "public"
        if not dsn:
            logger.warning("EVAL_JOB_STORAGE_BACKEND=postgres sin EVAL_JOB_POSTGRES_DSN; fallback sqlite")
            configured = "sqlite"
        else:
            try:
                return PostgresEvaluationJobStore(dsn=dsn, schema=schema)
            except Exception as exc:
                logger.warning("No se pudo iniciar PostgresEvaluationJobStore: %s; fallback sqlite", exc)
                configured = "sqlite"

    if configured == "sqlite":
        db_path = sqlite_db_path or str(
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "local_api.db"
        )
        try:
            return SQLiteEvaluationJobStore(db_path)
        except Exception as exc:
            logger.warning("No se pudo iniciar SQLiteEvaluationJobStore: %s; fallback memory", exc)
            return InMemoryEvaluationJobStore()

    return InMemoryEvaluationJobStore()


class EvaluationJobQueue:
    def enqueue(self, job_id: str) -> None:
        raise NotImplementedError

    def dequeue(self, timeout_seconds: int = 2) -> str | None:
        raise NotImplementedError


class InMemoryEvaluationJobQueue(EvaluationJobQueue):
    def __init__(self) -> None:
        self._queue: stdlib_queue.Queue[str] = stdlib_queue.Queue()

    def enqueue(self, job_id: str) -> None:
        self._queue.put(job_id)

    def dequeue(self, timeout_seconds: int = 2) -> str | None:
        try:
            return self._queue.get(timeout=timeout_seconds)
        except stdlib_queue.Empty:
            return None


class RedisEvaluationJobQueue(EvaluationJobQueue):
    def __init__(self, redis_url: str, key: str = "eval_job_queue") -> None:
        try:
            import redis
        except ImportError as exc:
            raise ImportError("redis no esta instalado para EVAL_JOB_QUEUE_BACKEND=redis") from exc
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.key = key

    def enqueue(self, job_id: str) -> None:
        self.client.rpush(self.key, job_id)

    def dequeue(self, timeout_seconds: int = 2) -> str | None:
        item = self.client.brpop(self.key, timeout=max(1, timeout_seconds))
        if not item:
            return None
        if isinstance(item, tuple) and len(item) == 2:
            return str(item[1])
        return None


def build_evaluation_job_queue_from_env() -> EvaluationJobQueue:
    configured = os.getenv("EVAL_JOB_QUEUE_BACKEND", "auto").strip().lower()
    if configured == "auto":
        configured = "redis" if os.getenv("REDIS_URL", "").strip() else "memory"

    if configured == "redis":
        redis_url = os.getenv("EVAL_JOB_QUEUE_REDIS_URL", "").strip() or os.getenv("REDIS_URL", "").strip()
        redis_key = os.getenv("EVAL_JOB_QUEUE_KEY", "eval_job_queue").strip() or "eval_job_queue"
        if not redis_url:
            logger.warning("EVAL_JOB_QUEUE_BACKEND=redis sin REDIS_URL; fallback memory")
            return InMemoryEvaluationJobQueue()
        try:
            return RedisEvaluationJobQueue(redis_url=redis_url, key=redis_key)
        except Exception as exc:
            logger.warning("No se pudo iniciar RedisEvaluationJobQueue: %s; fallback memory", exc)
            return InMemoryEvaluationJobQueue()

    return InMemoryEvaluationJobQueue()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
