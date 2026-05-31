from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from clasificacion_langchain.auth.repository import (
    RefreshTokenRecord,
    UserRecord,
)
from clasificacion_langchain.tenancy.repository import (
    MembershipRecord,
    OrganizationRecord,
)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteIdentityStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS organizations (
                    org_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    company_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memberships (
                    user_id TEXT NOT NULL,
                    org_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, org_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (org_id) REFERENCES organizations(org_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    token_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    org_id TEXT,
                    expires_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (org_id) REFERENCES organizations(org_id) ON DELETE SET NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memberships_user
                ON memberships (user_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user
                ON refresh_tokens (user_id)
                """
            )

    def create_user(self, email: str, password_hash: str) -> UserRecord:
        user_id = uuid4().hex
        normalized_email = email.strip().lower()
        created_at = _utcnow_iso()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users (user_id, email, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, normalized_email, password_hash, created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Email ya existe") from exc

        return UserRecord(
            user_id=user_id,
            email=normalized_email,
            password_hash=password_hash,
            created_at=datetime.fromisoformat(created_at),
        )

    def get_user_by_email(self, email: str) -> UserRecord | None:
        normalized_email = email.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
        if row is None:
            return None
        return UserRecord(
            user_id=row["user_id"],
            email=row["email"],
            password_hash=row["password_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return UserRecord(
            user_id=row["user_id"],
            email=row["email"],
            password_hash=row["password_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_token(
        self,
        token_id: str,
        user_id: str,
        org_id: str | None,
        expires_at: datetime,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO refresh_tokens (token_id, user_id, org_id, expires_at, revoked)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(token_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    org_id=excluded.org_id,
                    expires_at=excluded.expires_at,
                    revoked=0
                """,
                (token_id, user_id, org_id, expires_at.isoformat()),
            )

    def get_token(self, token_id: str) -> RefreshTokenRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM refresh_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()

        if row is None:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at <= datetime.now(UTC):
            return None

        return RefreshTokenRecord(
            token_id=row["token_id"],
            user_id=row["user_id"],
            org_id=row["org_id"],
            expires_at=expires_at,
            revoked=bool(row["revoked"]),
        )

    def revoke_token(self, token_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE token_id = ?",
                (token_id,),
            )

    def create_organization(self, name: str, company_id: str) -> OrganizationRecord:
        org_id = uuid4().hex
        normalized_company = company_id.strip().lower()
        created_at = _utcnow_iso()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO organizations (org_id, name, company_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (org_id, name.strip(), normalized_company, created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("company_id ya existe") from exc

        return OrganizationRecord(
            org_id=org_id,
            name=name.strip(),
            company_id=normalized_company,
            created_at=datetime.fromisoformat(created_at),
        )

    def get_organization(self, org_id: str) -> OrganizationRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM organizations WHERE org_id = ?",
                (org_id,),
            ).fetchone()
        if row is None:
            return None
        return OrganizationRecord(
            org_id=row["org_id"],
            name=row["name"],
            company_id=row["company_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_organization_by_company_id(self, company_id: str) -> OrganizationRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM organizations WHERE company_id = ?",
                (company_id.strip().lower(),),
            ).fetchone()
        if row is None:
            return None
        return OrganizationRecord(
            org_id=row["org_id"],
            name=row["name"],
            company_id=row["company_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def add_membership(self, user_id: str, org_id: str, role: str) -> MembershipRecord:
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memberships (user_id, org_id, role, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, org_id) DO NOTHING
                """,
                (user_id, org_id, role, now),
            )
            row = conn.execute(
                "SELECT * FROM memberships WHERE user_id = ? AND org_id = ?",
                (user_id, org_id),
            ).fetchone()

        assert row is not None
        return MembershipRecord(
            user_id=row["user_id"],
            org_id=row["org_id"],
            role=row["role"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_memberships(self, user_id: str) -> list[MembershipRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memberships WHERE user_id = ? ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        return [
            MembershipRecord(
                user_id=row["user_id"],
                org_id=row["org_id"],
                role=row["role"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
