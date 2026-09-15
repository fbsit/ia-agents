from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from clasificacion_langchain.agents.repository import AgentDocumentRecord, AgentRecord

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None
    BotoCoreError = Exception
    ClientError = Exception


def _safe_segment(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return "unknown"
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "unknown"


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


@dataclass
class StoredDocumentLocation:
    provider: str
    key: str


class DocumentStorage(Protocol):
    def save(
        self,
        agent: AgentRecord,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> StoredDocumentLocation:
        ...

    def read(self, document: AgentDocumentRecord) -> bytes:
        ...

    def delete(self, document: AgentDocumentRecord) -> None:
        ...


class LocalDocumentStorage:
    def __init__(self, knowledge_root: str | Path) -> None:
        self.knowledge_root = Path(knowledge_root)
        self.knowledge_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_path(key: str | None, fallback: str | None = None) -> Path:
        candidate = (key or fallback or "").strip()
        if not candidate:
            raise FileNotFoundError("storage_key vacio para proveedor local")
        return Path(candidate)

    def save(
        self,
        agent: AgentRecord,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> StoredDocumentLocation:
        del content_type
        target_dir = Path(agent.knowledge_dir) / agent.company_id
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        unique_suffix = uuid4().hex[:8]
        output_path = target_dir / f"{timestamp}-{unique_suffix}-{filename}"
        output_path.write_bytes(content)
        return StoredDocumentLocation(provider="local", key=str(output_path))

    def read(self, document: AgentDocumentRecord) -> bytes:
        path = self._resolve_path(document.storage_key, document.stored_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Documento no encontrado en storage local: {path}")
        return path.read_bytes()

    def delete(self, document: AgentDocumentRecord) -> None:
        path = self._resolve_path(document.storage_key, document.stored_path)
        if path.exists():
            path.unlink(missing_ok=True)


class S3DocumentStorage:
    def __init__(
        self,
        bucket: str,
        prefix: str = "agents",
        region_name: str | None = None,
        endpoint_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        if boto3 is None:
            raise RuntimeError(
                "S3 storage requiere boto3 instalado. Agrega boto3 a requirements.txt"
            )

        clean_bucket = bucket.strip()
        if not clean_bucket:
            raise ValueError("S3_BUCKET es requerido cuando DOC_STORAGE_BACKEND=s3")

        clean_prefix = prefix.strip().strip("/")
        if not clean_prefix:
            clean_prefix = "agents"

        self.bucket = clean_bucket
        self.prefix = clean_prefix
        client_kwargs: dict[str, Any] = {}
        if endpoint_url:
            # Endpoints S3-compatibles (RustFS, MinIO, R2) no resuelven <bucket>.<host>:
            # forzar direccionamiento por path. AWS real no necesita endpoint_url.
            from botocore.config import Config

            client_kwargs["config"] = Config(s3={"addressing_style": "path"})
        self.client = client or boto3.client(
            "s3",
            region_name=region_name or None,
            endpoint_url=endpoint_url or None,
            aws_access_key_id=_env_first("RUSTFS_ACCESS_KEY", "AWS_ACCESS_KEY_ID") or None,
            aws_secret_access_key=_env_first("RUSTFS_SECRET_KEY", "AWS_SECRET_ACCESS_KEY") or None,
            aws_session_token=os.getenv("AWS_SESSION_TOKEN") or None,
            **client_kwargs,
        )

    def _build_key(self, agent: AgentRecord, filename: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        unique_suffix = uuid4().hex[:8]
        org_id = _safe_segment(agent.org_id)
        company_id = _safe_segment(agent.company_id)
        agent_id = _safe_segment(agent.agent_id)
        safe_filename = _safe_segment(filename)
        return (
            f"{self.prefix}/{org_id}/{company_id}/{agent_id}/"
            f"{timestamp}-{unique_suffix}-{safe_filename}"
        )

    def save(
        self,
        agent: AgentRecord,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> StoredDocumentLocation:
        key = self._build_key(agent, filename)
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": content,
        }
        if content_type:
            kwargs["ContentType"] = content_type
        self.client.put_object(**kwargs)
        return StoredDocumentLocation(provider="s3", key=key)

    def read(self, document: AgentDocumentRecord) -> bytes:
        key = (document.storage_key or document.stored_path or "").strip()
        if not key:
            raise FileNotFoundError("storage_key vacio para proveedor s3")

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response.get("Body")
            if body is None:
                return b""
            return body.read()
        except (ClientError, BotoCoreError) as exc:
            raise FileNotFoundError(
                f"Documento no encontrado en S3 key={key}"
            ) from exc

    def delete(self, document: AgentDocumentRecord) -> None:
        key = (document.storage_key or document.stored_path or "").strip()
        if not key:
            return
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError):
            return

    # --- artefactos binarios (indices RAG) ------------------------------------

    def _artifact_key(self, agent_id: str) -> str:
        return f"{self.prefix}/indexes/{_safe_segment(agent_id)}.joblib"

    def upload_artifact(self, agent_id: str, local_path: Path) -> str:
        key = self._artifact_key(agent_id)
        self.client.upload_file(str(local_path), self.bucket, key)
        return key

    def download_artifact(self, agent_id: str, local_path: Path) -> bool:
        key = self._artifact_key(agent_id)
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(self.bucket, key, str(local_path))
            return True
        except (ClientError, BotoCoreError):
            return False

    def delete_artifact(self, agent_id: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._artifact_key(agent_id))
        except (ClientError, BotoCoreError):
            return


class RoutedDocumentStorage:
    def __init__(
        self,
        default_backend: str,
        local_storage: LocalDocumentStorage,
        s3_storage: S3DocumentStorage | None,
    ) -> None:
        self.default_backend = default_backend
        self.local_storage = local_storage
        self.s3_storage = s3_storage

    @property
    def artifact_store(self) -> S3DocumentStorage | None:
        # Store remoto para indices RAG; solo cuando el backend por defecto es s3.
        if self.default_backend == "s3" and self.s3_storage is not None:
            return self.s3_storage
        return None

    def upload_index(self, agent_id: str, local_path: Path) -> str | None:
        store = self.artifact_store
        return store.upload_artifact(agent_id, local_path) if store is not None else None

    def ensure_index_local(self, agent_id: str, local_path: Path) -> bool:
        # Garantiza el joblib en disco: si no esta, lo baja del store remoto (filesystem efimero).
        if local_path.exists():
            return True
        store = self.artifact_store
        return store.download_artifact(agent_id, local_path) if store is not None else False

    def delete_index(self, agent_id: str) -> None:
        store = self.artifact_store
        if store is not None:
            store.delete_artifact(agent_id)

    def _storage_for_provider(self, provider: str) -> DocumentStorage:
        normalized = provider.strip().lower()
        if normalized == "s3":
            if self.s3_storage is None:
                raise RuntimeError(
                    "storage_provider=s3 pero S3 storage no esta configurado"
                )
            return self.s3_storage
        return self.local_storage

    def save(
        self,
        agent: AgentRecord,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> StoredDocumentLocation:
        storage = self._storage_for_provider(self.default_backend)
        return storage.save(
            agent=agent,
            filename=filename,
            content=content,
            content_type=content_type,
        )

    def read(self, document: AgentDocumentRecord) -> bytes:
        provider = (document.storage_provider or "local").strip().lower()
        storage = self._storage_for_provider(provider)
        return storage.read(document)

    def delete(self, document: AgentDocumentRecord) -> None:
        provider = (document.storage_provider or "local").strip().lower()
        storage = self._storage_for_provider(provider)
        storage.delete(document)


def build_document_storage_from_env(knowledge_root: str | Path) -> RoutedDocumentStorage:
    backend = os.getenv("DOC_STORAGE_BACKEND", "local").strip().lower()
    if backend not in {"local", "s3"}:
        backend = "local"

    local_storage = LocalDocumentStorage(knowledge_root=knowledge_root)
    s3_storage: S3DocumentStorage | None = None

    if backend == "s3":
        bucket = _env_first("RUSTFS_BUCKET", "S3_BUCKET")
        region_name = _env_first("RUSTFS_REGION", "S3_REGION") or None
        endpoint_url = _env_first("RUSTFS_ENDPOINT", "S3_ENDPOINT_URL") or None
        s3_storage = S3DocumentStorage(
            bucket=bucket,
            prefix=os.getenv("S3_PREFIX", "agents"),
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

    return RoutedDocumentStorage(
        default_backend=backend,
        local_storage=local_storage,
        s3_storage=s3_storage,
    )
