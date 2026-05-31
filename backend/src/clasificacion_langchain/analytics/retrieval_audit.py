from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalAuditRecord:
    company_id: str
    agent_id: str
    channel: str
    route: str | None
    response_mode: str | None
    retrieved_chunks: int
    sources_count: int
    avg_retrieval_score: float | None
    max_retrieval_score: float | None
    min_score_threshold: float | None
    fallback_applied: bool
    latency_ms: int
    rag_backend: str


@dataclass(frozen=True)
class RetrievalAuditSummaryRow:
    company_id: str
    agent_id: str
    queries_total: int
    answers_with_sources: int
    answers_without_sources: int
    fallback_count: int
    avg_retrieved_chunks: float
    avg_retrieval_score: float
    avg_latency_ms: float


@dataclass(frozen=True)
class RetrievalBackendMetrics:
    backend: str
    queries_total: int
    answers_with_sources: int
    fallback_count: int
    avg_retrieval_score: float
    avg_latency_ms: float


@dataclass(frozen=True)
class RetrievalComparisonRow:
    company_id: str
    agent_id: str
    current_backend: str
    baseline_backend: str | None
    current: RetrievalBackendMetrics
    baseline: RetrievalBackendMetrics | None
    grounded_rate_delta: float | None
    fallback_rate_delta: float | None
    score_delta: float | None
    latency_delta_ms: float | None


class InMemoryRetrievalAuditStore:
    def __init__(self, max_rows: int = 5000) -> None:
        self._rows: list[tuple[datetime, RetrievalAuditRecord]] = []
        self._max_rows = max(100, max_rows)

    def record(self, record: RetrievalAuditRecord) -> None:
        self._rows.append((datetime.now(UTC), record))
        overflow = len(self._rows) - self._max_rows
        if overflow > 0:
            del self._rows[:overflow]

    def summary(self, company_id: str | None = None, since_days: int = 30) -> list[RetrievalAuditSummaryRow]:
        cutoff = datetime.now(UTC) - timedelta(days=max(1, since_days))
        buckets: dict[tuple[str, str], dict[str, float]] = {}

        for created_at, record in self._rows:
            if created_at < cutoff:
                continue
            if company_id and record.company_id != company_id:
                continue

            key = (record.company_id, record.agent_id)
            if key not in buckets:
                buckets[key] = {
                    "queries_total": 0.0,
                    "answers_with_sources": 0.0,
                    "answers_without_sources": 0.0,
                    "fallback_count": 0.0,
                    "retrieved_chunks_sum": 0.0,
                    "retrieval_score_sum": 0.0,
                    "retrieval_score_count": 0.0,
                    "latency_sum": 0.0,
                }

            bucket = buckets[key]
            bucket["queries_total"] += 1
            bucket["retrieved_chunks_sum"] += float(record.retrieved_chunks)
            bucket["latency_sum"] += float(record.latency_ms)

            if record.sources_count > 0:
                bucket["answers_with_sources"] += 1
            else:
                bucket["answers_without_sources"] += 1

            if record.fallback_applied:
                bucket["fallback_count"] += 1

            if record.avg_retrieval_score is not None:
                bucket["retrieval_score_sum"] += float(record.avg_retrieval_score)
                bucket["retrieval_score_count"] += 1

        output: list[RetrievalAuditSummaryRow] = []
        for (row_company_id, row_agent_id), metrics in sorted(buckets.items()):
            total = max(int(metrics["queries_total"]), 1)
            score_count = max(int(metrics["retrieval_score_count"]), 1)
            output.append(
                RetrievalAuditSummaryRow(
                    company_id=row_company_id,
                    agent_id=row_agent_id,
                    queries_total=int(metrics["queries_total"]),
                    answers_with_sources=int(metrics["answers_with_sources"]),
                    answers_without_sources=int(metrics["answers_without_sources"]),
                    fallback_count=int(metrics["fallback_count"]),
                    avg_retrieved_chunks=round(metrics["retrieved_chunks_sum"] / total, 4),
                    avg_retrieval_score=round(metrics["retrieval_score_sum"] / score_count, 6),
                    avg_latency_ms=round(metrics["latency_sum"] / total, 2),
                )
            )
        return output

    @staticmethod
    def _build_backend_metrics(backend: str, records: list[RetrievalAuditRecord]) -> RetrievalBackendMetrics:
        total = len(records)
        with_sources = len([record for record in records if record.sources_count > 0])
        fallback_count = len([record for record in records if record.fallback_applied])
        scored = [record.avg_retrieval_score for record in records if record.avg_retrieval_score is not None]
        avg_score = sum(scored) / len(scored) if scored else 0.0
        avg_latency = sum(record.latency_ms for record in records) / max(total, 1)
        return RetrievalBackendMetrics(
            backend=backend,
            queries_total=total,
            answers_with_sources=with_sources,
            fallback_count=fallback_count,
            avg_retrieval_score=round(avg_score, 6),
            avg_latency_ms=round(avg_latency, 2),
        )

    def compare_agent_backends(
        self,
        company_id: str,
        agent_id: str,
        current_backend: str,
        since_days: int = 30,
    ) -> RetrievalComparisonRow:
        cutoff = datetime.now(UTC) - timedelta(days=max(1, since_days))
        selected = [
            record
            for created_at, record in self._rows
            if created_at >= cutoff and record.company_id == company_id and record.agent_id == agent_id
        ]

        current_rows = [record for record in selected if record.rag_backend == current_backend]
        current_metrics = self._build_backend_metrics(current_backend, current_rows)

        baseline_backend: str | None = None
        baseline_rows: list[RetrievalAuditRecord] = []
        for record in reversed(selected):
            if record.rag_backend == current_backend:
                continue
            baseline_backend = record.rag_backend
            break

        if baseline_backend is not None:
            baseline_rows = [record for record in selected if record.rag_backend == baseline_backend]

        baseline_metrics = (
            self._build_backend_metrics(baseline_backend, baseline_rows)
            if baseline_backend is not None
            else None
        )

        if baseline_metrics is None:
            return RetrievalComparisonRow(
                company_id=company_id,
                agent_id=agent_id,
                current_backend=current_backend,
                baseline_backend=None,
                current=current_metrics,
                baseline=None,
                grounded_rate_delta=None,
                fallback_rate_delta=None,
                score_delta=None,
                latency_delta_ms=None,
            )

        current_grounded_rate = current_metrics.answers_with_sources / max(current_metrics.queries_total, 1)
        baseline_grounded_rate = baseline_metrics.answers_with_sources / max(baseline_metrics.queries_total, 1)
        current_fallback_rate = current_metrics.fallback_count / max(current_metrics.queries_total, 1)
        baseline_fallback_rate = baseline_metrics.fallback_count / max(baseline_metrics.queries_total, 1)

        return RetrievalComparisonRow(
            company_id=company_id,
            agent_id=agent_id,
            current_backend=current_backend,
            baseline_backend=baseline_backend,
            current=current_metrics,
            baseline=baseline_metrics,
            grounded_rate_delta=round(current_grounded_rate - baseline_grounded_rate, 6),
            fallback_rate_delta=round(current_fallback_rate - baseline_fallback_rate, 6),
            score_delta=round(current_metrics.avg_retrieval_score - baseline_metrics.avg_retrieval_score, 6),
            latency_delta_ms=round(current_metrics.avg_latency_ms - baseline_metrics.avg_latency_ms, 2),
        )


class RetrievalAuditService:
    def __init__(self, store: InMemoryRetrievalAuditStore | None) -> None:
        self.store = store

    def enabled(self) -> bool:
        return self.store is not None

    def record(self, record: RetrievalAuditRecord) -> None:
        if self.store is None:
            return
        self.store.record(record)

    def summary(self, company_id: str | None = None, since_days: int = 30) -> list[RetrievalAuditSummaryRow]:
        if self.store is None:
            return []
        return self.store.summary(company_id=company_id, since_days=since_days)

    def compare_agent_backends(
        self,
        company_id: str,
        agent_id: str,
        current_backend: str,
        since_days: int = 30,
    ) -> RetrievalComparisonRow:
        if self.store is None:
            current = RetrievalBackendMetrics(
                backend=current_backend,
                queries_total=0,
                answers_with_sources=0,
                fallback_count=0,
                avg_retrieval_score=0.0,
                avg_latency_ms=0.0,
            )
            return RetrievalComparisonRow(
                company_id=company_id,
                agent_id=agent_id,
                current_backend=current_backend,
                baseline_backend=None,
                current=current,
                baseline=None,
                grounded_rate_delta=None,
                fallback_rate_delta=None,
                score_delta=None,
                latency_delta_ms=None,
            )
        return self.store.compare_agent_backends(
            company_id=company_id,
            agent_id=agent_id,
            current_backend=current_backend,
            since_days=since_days,
        )


def build_retrieval_audit_service_from_env() -> RetrievalAuditService:
    backend = os.getenv("RETRIEVAL_AUDIT_BACKEND", "memory").strip().lower()

    if backend in {"", "none", "off", "disabled"}:
        return RetrievalAuditService(store=None)

    if backend == "memory":
        max_rows_raw = os.getenv("RETRIEVAL_AUDIT_MAX_ROWS", "5000").strip()
        try:
            max_rows = int(max_rows_raw)
        except ValueError:
            max_rows = 5000
        return RetrievalAuditService(store=InMemoryRetrievalAuditStore(max_rows=max_rows))

    logger.warning("retrieval_audit_disabled reason=unknown_backend backend=%s", backend)
    return RetrievalAuditService(store=None)
