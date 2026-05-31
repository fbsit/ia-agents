from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SessionTurn:
    role: str
    text: str


class SessionStore(Protocol):
    def append_user_message(self, company_id: str, session_id: str, text: str) -> None:
        ...

    def append_assistant_message(self, company_id: str, session_id: str, text: str) -> None:
        ...

    def recent_turns(
        self,
        company_id: str,
        session_id: str,
        limit: int = 4,
    ) -> list[SessionTurn]:
        ...
