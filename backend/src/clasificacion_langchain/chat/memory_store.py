from __future__ import annotations

from dataclasses import dataclass, field

from clasificacion_langchain.chat.session_store import SessionSummary, SessionTurn, StoredSessionSummary


@dataclass
class SessionContext:
    company_id: str
    session_id: str
    turns: list[SessionTurn] = field(default_factory=list)
    summary: SessionSummary = field(default_factory=SessionSummary)


class InMemorySessionStore:
    def __init__(self, max_turns: int = 12) -> None:
        self.max_turns = max_turns
        self._sessions: dict[tuple[str, str], SessionContext] = {}

    def _key(self, company_id: str, session_id: str) -> tuple[str, str]:
        return company_id.strip(), session_id.strip()

    def get_context(self, company_id: str, session_id: str) -> SessionContext:
        key = self._key(company_id, session_id)
        if key not in self._sessions:
            self._sessions[key] = SessionContext(company_id=key[0], session_id=key[1])
        return self._sessions[key]

    def append_user_message(self, company_id: str, session_id: str, text: str) -> None:
        context = self.get_context(company_id, session_id)
        context.turns.append(SessionTurn(role="user", text=text))
        self._truncate(context)

    def append_assistant_message(self, company_id: str, session_id: str, text: str) -> None:
        context = self.get_context(company_id, session_id)
        context.turns.append(SessionTurn(role="assistant", text=text))
        self._truncate(context)

    def recent_turns(
        self,
        company_id: str,
        session_id: str,
        limit: int = 4,
    ) -> list[SessionTurn]:
        context = self.get_context(company_id, session_id)
        if limit <= 0:
            return []
        return context.turns[-limit:]

    def get_summary(self, company_id: str, session_id: str) -> SessionSummary:
        context = self.get_context(company_id, session_id)
        return context.summary

    def save_summary(self, company_id: str, session_id: str, summary: SessionSummary) -> None:
        context = self.get_context(company_id, session_id)
        context.summary = summary

    def list_summaries(self) -> list[StoredSessionSummary]:
        return [
            StoredSessionSummary(
                company_id=context.company_id,
                session_id=context.session_id,
                summary=context.summary,
            )
            for context in self._sessions.values()
        ]

    def _truncate(self, context: SessionContext) -> None:
        if len(context.turns) > self.max_turns:
            context.turns = context.turns[-self.max_turns :]
