from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from clasificacion_langchain.auth.repository import RefreshTokenRecord, UserRecord
from clasificacion_langchain.tenancy.repository import MembershipRecord, OrganizationRecord
from clasificacion_langchain.persistence.pg_connections import pooled_connection


def _to_epoch_seconds(value: datetime) -> int:
    return int(value.timestamp())


def _from_epoch_seconds(value: int | float | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return datetime.fromtimestamp(float(value), tz=UTC)


class PostgresIdentityStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        try:
            import psycopg  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "psycopg no esta instalado para PERSISTENCE_BACKEND=postgres"
            ) from exc
        self._psycopg = psycopg
        self._ensure_schema()

    def _connect(self):
        return pooled_connection(self._psycopg, self.dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        created_at BIGINT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS organizations (
                        org_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        company_id TEXT NOT NULL UNIQUE,
                        created_at BIGINT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memberships (
                        user_id TEXT NOT NULL,
                        org_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        PRIMARY KEY (user_id, org_id),
                        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                        FOREIGN KEY (org_id) REFERENCES organizations(org_id) ON DELETE CASCADE
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS refresh_tokens (
                        token_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        org_id TEXT,
                        expires_at BIGINT NOT NULL,
                        revoked BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT,
                        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                        FOREIGN KEY (org_id) REFERENCES organizations(org_id) ON DELETE SET NULL
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS org_id TEXT"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memberships_user ON memberships (user_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens (user_id)"
                )
            conn.commit()

    def create_user(self, email: str, password_hash: str) -> UserRecord:
        user_id = uuid4().hex
        normalized_email = email.strip().lower()
        created_at = int(datetime.now(UTC).timestamp())
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users (user_id, email, password_hash, created_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (user_id, normalized_email, password_hash, created_at),
                    )
                conn.commit()
        except self._psycopg.IntegrityError as exc:
            raise ValueError("Email ya existe") from exc

        return UserRecord(
            user_id=user_id,
            email=normalized_email,
            password_hash=password_hash,
            created_at=_from_epoch_seconds(created_at),
        )

    def get_user_by_email(self, email: str) -> UserRecord | None:
        normalized_email = email.strip().lower()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id, email, password_hash, created_at FROM users WHERE email = %s", (normalized_email,))
                row = cur.fetchone()
        if row is None:
            return None
        return UserRecord(
            user_id=row[0],
            email=row[1],
            password_hash=row[2],
            created_at=_from_epoch_seconds(row[3]),
        )

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id, email, password_hash, created_at FROM users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return UserRecord(
            user_id=row[0],
            email=row[1],
            password_hash=row[2],
            created_at=_from_epoch_seconds(row[3]),
        )

    def save_token(
        self,
        token_id: str,
        user_id: str,
        org_id: str | None,
        expires_at: datetime,
    ) -> None:
        expires_epoch = _to_epoch_seconds(expires_at)
        now_epoch = int(datetime.now(UTC).timestamp())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO refresh_tokens (token_id, user_id, org_id, expires_at, revoked, created_at)
                    VALUES (%s, %s, %s, %s, FALSE, %s)
                    ON CONFLICT(token_id) DO UPDATE SET
                        user_id=EXCLUDED.user_id,
                        org_id=EXCLUDED.org_id,
                        expires_at=EXCLUDED.expires_at,
                        revoked=FALSE
                    """,
                    (token_id, user_id, org_id, expires_epoch, now_epoch),
                )
            conn.commit()

    def get_token(self, token_id: str) -> RefreshTokenRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT token_id, user_id, org_id, expires_at, revoked FROM refresh_tokens WHERE token_id = %s",
                    (token_id,),
                )
                row = cur.fetchone()

        if row is None:
            return None

        expires_at = _from_epoch_seconds(row[3])
        if expires_at <= datetime.now(UTC):
            return None

        return RefreshTokenRecord(
            token_id=row[0],
            user_id=row[1],
            org_id=row[2],
            expires_at=expires_at,
            revoked=bool(row[4]),
        )

    def revoke_token(self, token_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE refresh_tokens SET revoked = TRUE WHERE token_id = %s",
                    (token_id,),
                )
            conn.commit()

    def create_organization(self, name: str, company_id: str) -> OrganizationRecord:
        org_id = uuid4().hex
        normalized_company = company_id.strip().lower()
        created_at = int(datetime.now(UTC).timestamp())
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO organizations (org_id, name, company_id, created_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (org_id, name.strip(), normalized_company, created_at),
                    )
                conn.commit()
        except self._psycopg.IntegrityError as exc:
            raise ValueError("company_id ya existe") from exc

        return OrganizationRecord(
            org_id=org_id,
            name=name.strip(),
            company_id=normalized_company,
            created_at=_from_epoch_seconds(created_at),
        )

    def get_organization(self, org_id: str) -> OrganizationRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT org_id, name, company_id, created_at FROM organizations WHERE org_id = %s",
                    (org_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return OrganizationRecord(
            org_id=row[0],
            name=row[1],
            company_id=row[2],
            created_at=_from_epoch_seconds(row[3]),
        )

    def get_organization_by_company_id(self, company_id: str) -> OrganizationRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT org_id, name, company_id, created_at FROM organizations WHERE company_id = %s",
                    (company_id.strip().lower(),),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return OrganizationRecord(
            org_id=row[0],
            name=row[1],
            company_id=row[2],
            created_at=_from_epoch_seconds(row[3]),
        )

    def add_membership(self, user_id: str, org_id: str, role: str) -> MembershipRecord:
        now_epoch = int(datetime.now(UTC).timestamp())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memberships (user_id, org_id, role, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(user_id, org_id) DO NOTHING
                    """,
                    (user_id, org_id, role, now_epoch),
                )
                cur.execute(
                    "SELECT user_id, org_id, role, created_at FROM memberships WHERE user_id = %s AND org_id = %s",
                    (user_id, org_id),
                )
                row = cur.fetchone()
            conn.commit()

        assert row is not None
        return MembershipRecord(
            user_id=row[0],
            org_id=row[1],
            role=row[2],
            created_at=_from_epoch_seconds(row[3]),
        )

    def list_memberships(self, user_id: str) -> list[MembershipRecord]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id, org_id, role, created_at FROM memberships WHERE user_id = %s ORDER BY created_at ASC",
                    (user_id,),
                )
                rows = cur.fetchall()
        return [
            MembershipRecord(
                user_id=row[0],
                org_id=row[1],
                role=row[2],
                created_at=_from_epoch_seconds(row[3]),
            )
            for row in rows
        ]
