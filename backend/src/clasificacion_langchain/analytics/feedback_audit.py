from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentFeedbackRecord:
    company_id: str
    agent_id: str
    rating: str
    question: str
    answer: str
    sources: list[str]
    comment: str | None = None
    expected_answer: str | None = None
    session_id: str | None = None
    source_channel: str | None = None


@dataclass(frozen=True)
class AgentFeedbackSummary:
    company_id: str
    agent_id: str
    feedback_total: int
    thumbs_up: int
    thumbs_down: int
    positive_rate: float
    with_comment: int
    with_expected_answer: int


class InMemoryAgentFeedbackStore:
    def __init__(self, max_rows: int = 5000) -> None:
        self._rows: list[tuple[datetime, AgentFeedbackRecord]] = []
        self._max_rows = max(100, max_rows)

    def record(self, record: AgentFeedbackRecord) -> None:
        self._rows.append((datetime.now(UTC), record))
        overflow = len(self._rows) - self._max_rows
        if overflow > 0:
            del self._rows[:overflow]

    def summary(
        self,
        company_id: str,
        agent_id: str,
        since_days: int = 30,
    ) -> AgentFeedbackSummary:
        cutoff = datetime.now(UTC) - timedelta(days=max(1, since_days))
        selected = [
            row
            for created_at, row in self._rows
            if created_at >= cutoff and row.company_id == company_id and row.agent_id == agent_id
        ]

        total = len(selected)
        thumbs_up = len([row for row in selected if row.rating == "up"])
        thumbs_down = len([row for row in selected if row.rating == "down"])
        with_comment = len([row for row in selected if (row.comment or "").strip()])
        with_expected_answer = len([row for row in selected if (row.expected_answer or "").strip()])
        positive_rate = round(thumbs_up / max(total, 1), 6)

        return AgentFeedbackSummary(
            company_id=company_id,
            agent_id=agent_id,
            feedback_total=total,
            thumbs_up=thumbs_up,
            thumbs_down=thumbs_down,
            positive_rate=positive_rate,
            with_comment=with_comment,
            with_expected_answer=with_expected_answer,
        )


class AgentFeedbackService:
    def __init__(self, store: InMemoryAgentFeedbackStore | None) -> None:
        self.store = store

    def enabled(self) -> bool:
        return self.store is not None

    def record(self, record: AgentFeedbackRecord) -> None:
        if self.store is None:
            return
        self.store.record(record)

    def summary(
        self,
        company_id: str,
        agent_id: str,
        since_days: int = 30,
    ) -> AgentFeedbackSummary:
        if self.store is None:
            return AgentFeedbackSummary(
                company_id=company_id,
                agent_id=agent_id,
                feedback_total=0,
                thumbs_up=0,
                thumbs_down=0,
                positive_rate=0.0,
                with_comment=0,
                with_expected_answer=0,
            )
        return self.store.summary(company_id=company_id, agent_id=agent_id, since_days=since_days)


def build_agent_feedback_service_from_env() -> AgentFeedbackService:
    backend = os.getenv("AGENT_FEEDBACK_BACKEND", "memory").strip().lower()

    if backend in {"", "none", "off", "disabled"}:
        return AgentFeedbackService(store=None)

    if backend == "memory":
        max_rows_raw = os.getenv("AGENT_FEEDBACK_MAX_ROWS", "5000").strip()
        try:
            max_rows = int(max_rows_raw)
        except ValueError:
            max_rows = 5000
        return AgentFeedbackService(store=InMemoryAgentFeedbackStore(max_rows=max_rows))

    logger.warning("agent_feedback_disabled reason=unknown_backend backend=%s", backend)
    return AgentFeedbackService(store=None)
