from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib import error as urllib_error, request as urllib_request
from uuid import uuid4

from clasificacion_langchain.agents.repository import (
    AgentDocumentRecord,
    AgentRepository,
    AgentRecord,
)
from clasificacion_langchain.agents.document_storage import (
    DocumentStorage,
    build_document_storage_from_env,
)
from clasificacion_langchain.agents.orchestrator import (
    AgentIntentOrchestrator,
    OrchestrationDecision,
)
from clasificacion_langchain.agents.commerce_workflow import (
    build_state as build_workflow_state,
    normalize_stage,
    resolve_transition,
)
from clasificacion_langchain.agents.conversation_policy import (
    ConversationKey,
    ConversationPolicyEngine,
)
from clasificacion_langchain.agents.role_knowledge import (
    RoleContext,
    build_role_context,
    sync_shared_knowledge,
)
from clasificacion_langchain.chat.memory_store import InMemorySessionStore
from clasificacion_langchain.chat.session_store import SessionStore, SessionSummary
from clasificacion_langchain.rag.chunking import chunk_documents
from clasificacion_langchain.rag.dense_index import DenseVectorIndex
from clasificacion_langchain.rag.hybrid_index import HybridVectorIndex
from clasificacion_langchain.rag.generation import (
    ExtractiveAnswerGenerator,
    build_remote_generator,
    enforce_channel_response_contract,
    tune_answer_style,
)
from clasificacion_langchain.rag.loaders import load_text_content
from clasificacion_langchain.rag.pipeline import (
    IndexBuildResult,
    RAGPipeline,
)
from clasificacion_langchain.rag.schemas import KnowledgeDocument, RAGAnswer
from clasificacion_langchain.rag.vector_index import TfidfVectorIndex
from clasificacion_langchain.settings.service import TenantLlmSettingsService


SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".pdf", ".docx"}
SUPPORTED_GENERATION_PROVIDERS = {"auto", "openai", "anthropic"}
SUPPORTED_RAG_BACKENDS = {"auto", "tfidf", "dense_openai", "hybrid"}
SUPPORTED_OPERATIONAL_SECTIONS = {
    "facts",
    "rules",
    "contracts",
    "permissions",
    "feedback",
}
logger = logging.getLogger(__name__)


def _load_cart_snapshot(raw: str | None) -> list[dict[str, object]]:
    clean = str(raw or "").strip()
    if not clean:
        return []
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        product_id = str(item.get("product_id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not product_id or not name:
            continue
        try:
            quantity = max(0, int(item.get("quantity") or 0))
        except (TypeError, ValueError):
            quantity = 0
        rows.append(
            {
                "product_id": product_id,
                "name": name,
                "quantity": quantity,
                "price": str(item.get("price") or "").strip(),
            }
        )
    return rows


def _dump_cart_snapshot(items: list[dict[str, object]]) -> str:
    normalized = [item for item in items if int(item.get("quantity") or 0) > 0]
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")) if normalized else ""


def _apply_cart_actions_to_snapshot(
    current_snapshot: str | None,
    cart_actions: list[dict[str, object]] | None,
) -> str | None:
    if not cart_actions:
        return None
    items = _load_cart_snapshot(current_snapshot)
    by_product = {str(item.get("product_id") or ""): dict(item) for item in items}
    for action in cart_actions:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("type") or "").strip().lower()
        if action_type == "clear_cart":
            by_product = {}
            continue
        item = action.get("item") if isinstance(action.get("item"), dict) else {}
        product_id = str(item.get("checkout_product_id") or item.get("product_id") or item.get("variant_id") or "").strip()
        name = str(item.get("name") or "Producto").strip() or "Producto"
        try:
            quantity = max(0, int(item.get("quantity") or 0))
        except (TypeError, ValueError):
            quantity = 0
        if not product_id:
            continue
        current = by_product.get(
            product_id,
            {
                "product_id": product_id,
                "name": name,
                "quantity": 0,
                "price": str(item.get("price") or "").strip(),
            },
        )
        current["name"] = name
        if str(item.get("price") or "").strip():
            current["price"] = str(item.get("price") or "").strip()
        current_quantity = max(0, int(current.get("quantity") or 0))
        if action_type == "add_to_cart":
            current["quantity"] = current_quantity + max(1, quantity)
        elif action_type == "remove_from_cart":
            current["quantity"] = max(0, current_quantity - max(1, quantity))
        elif action_type == "set_cart_quantity":
            current["quantity"] = quantity
        if int(current.get("quantity") or 0) > 0:
            by_product[product_id] = current
        else:
            by_product.pop(product_id, None)
    return _dump_cart_snapshot(list(by_product.values()))
logger.setLevel(logging.INFO)


def _format_history_for_query(history: list[tuple[str, str]]) -> str:
    if not history:
        return ""

    lines = ["Contexto breve de conversacion previa:"]
    for role, text in history:
        role_name = "Usuario" if role == "user" else "Asistente"
        lines.append(f"- {role_name}: {_truncate_memory_text(text, limit=140)}")
    return "\n".join(lines)


def _truncate_memory_text(text: str, limit: int = 180) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _summarize_history_for_query(history: list[tuple[str, str]], max_items: int = 4) -> str:
    if not history:
        return ""

    lines = ["Resumen operativo de la conversacion:"]
    recent_user_messages = [text for role, text in history if role == "user"][-2:]
    recent_assistant_messages = [text for role, text in history if role != "user"][-2:]

    for text in recent_user_messages[:max_items]:
        clean = _truncate_memory_text(text)
        if clean:
            lines.append(f"- Ultima necesidad del usuario: {clean}")

    for text in recent_assistant_messages[:max_items]:
        clean = _truncate_memory_text(text)
        if clean:
            lines.append(f"- Ultima respuesta/compromiso del agente: {clean}")

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _format_session_summary(summary: SessionSummary) -> str:
    lines: list[str] = []
    if summary.user_goal:
        lines.append(f"- Objetivo actual del usuario: {_truncate_memory_text(summary.user_goal, 180)}")
    if summary.funnel_stage:
        lines.append(f"- Etapa comercial actual: {summary.funnel_stage}")
    if summary.checkout_stage:
        lines.append(f"- Subetapa checkout: {summary.checkout_stage}")
    if summary.pending_next_step:
        lines.append(f"- Siguiente paso sugerido: {summary.pending_next_step}")
    if summary.selected_products:
        lines.append(f"- Productos relevantes: {_truncate_memory_text(summary.selected_products, 180)}")
    elif summary.last_product_query:
        lines.append(f"- Ultima busqueda de producto: {_truncate_memory_text(summary.last_product_query, 140)}")
    if summary.shipping_preference:
        lines.append(f"- Preferencia de despacho: {_truncate_memory_text(summary.shipping_preference, 120)}")
    if summary.pickup_location_label:
        lines.append(f"- Punto de retiro elegido: {_truncate_memory_text(summary.pickup_location_label, 120)}")
    if summary.delivery_address:
        status = "confirmada" if summary.delivery_address_confirmed else "pendiente de confirmacion"
        lines.append(f"- Direccion de despacho ({status}): {_truncate_memory_text(summary.delivery_address, 160)}")
    if summary.payment_preference:
        lines.append(f"- Preferencia de pago: {_truncate_memory_text(summary.payment_preference, 120)}")
    if summary.customer_authenticated:
        lines.append("- El cliente confirmo que inicio sesion")
    if summary.order_reference:
        lines.append(f"- Pedido/orden referenciada: {summary.order_reference}")
    if summary.last_action:
        lines.append(f"- Ultima accion relevante: {_truncate_memory_text(summary.last_action, 160)}")
    if summary.notes:
        lines.append(f"- Nota operativa: {_truncate_memory_text(summary.notes, 180)}")
    if not lines:
        return ""
    return "Resumen persistente de la sesion:\n" + "\n".join(lines)


def _normalize_summary_value(text: str, limit: int = 160) -> str:
    return _truncate_memory_text(text, limit)


def _normalize_rag_backend(value: str) -> str:
    raw = (value or "").strip().lower()
    aliases = {
        "hybrid_openai": "hybrid",
        "hybrid (tfidf + dense)": "hybrid",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in SUPPORTED_RAG_BACKENDS:
        raise AgentValidationError("rag_backend invalido")
    return normalized


def _canonical_document_filename(filename: str) -> str:
    normalized = (filename or "").strip().lower()
    if not normalized:
        return ""
    return re.sub(r"^\d{8}t\d{6,}-", "", normalized)


class AgentNotFoundError(Exception):
    pass


class AgentForbiddenError(Exception):
    pass


class AgentValidationError(Exception):
    pass


class AgentDocumentNotFoundError(Exception):
    pass


class AgentService:
    def __init__(
        self,
        repository: AgentRepository,
        llm_settings_service: TenantLlmSettingsService | None = None,
        orchestrator: AgentIntentOrchestrator | None = None,
        conversation_policy: ConversationPolicyEngine | None = None,
        session_store: SessionStore | None = None,
        knowledge_root: str | Path = "knowledge_base/agents",
        index_root: str | Path = "models/agents",
        document_storage: DocumentStorage | None = None,
    ) -> None:
        self.repository = repository
        self.llm_settings_service = llm_settings_service
        self.orchestrator = orchestrator or AgentIntentOrchestrator()
        self.conversation_policy = conversation_policy
        self.knowledge_root = Path(knowledge_root)
        self.index_root = Path(index_root)
        self.knowledge_root.mkdir(parents=True, exist_ok=True)
        self.index_root.mkdir(parents=True, exist_ok=True)
        max_session_turns = int(os.getenv("AGENT_CHAT_MAX_SESSION_TURNS", "12"))
        if max_session_turns < 2:
            max_session_turns = 2
        self.session_store = session_store or InMemorySessionStore(
            max_turns=max_session_turns
        )
        history_window = int(os.getenv("AGENT_CHAT_HISTORY_WINDOW", "4"))
        self.history_window = max(0, history_window)
        self.document_storage = document_storage or build_document_storage_from_env(
            knowledge_root=self.knowledge_root
        )
        self.eval_storage_backend = os.getenv("EVAL_STORAGE_BACKEND", "file").strip().lower() or "file"
        self.eval_postgres_dsn = os.getenv("EVAL_POSTGRES_DSN", "").strip()
        self.eval_postgres_schema = os.getenv("EVAL_POSTGRES_SCHEMA", "public").strip() or "public"
        self._eval_psycopg = None
        self._init_evaluation_storage()

    def _init_evaluation_storage(self) -> None:
        if self.eval_storage_backend != "postgres":
            return

        if not self.eval_postgres_dsn:
            logger.warning("eval_storage_backend=postgres but EVAL_POSTGRES_DSN is empty; fallback to file")
            self.eval_storage_backend = "file"
            return

        try:
            import psycopg  # type: ignore
        except ImportError:
            logger.warning("psycopg not installed; evaluation storage fallback to file")
            self.eval_storage_backend = "file"
            return

        self._eval_psycopg = psycopg
        self._ensure_eval_postgres_schema()

    def _eval_pg_connect(self):
        if self._eval_psycopg is None:
            raise AgentValidationError("Eval Postgres no disponible")
        return self._eval_psycopg.connect(self.eval_postgres_dsn)

    def _ensure_eval_postgres_schema(self) -> None:
        if self.eval_storage_backend != "postgres":
            return
        with self._eval_pg_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.eval_postgres_schema}.agent_eval_datasets (
                        company_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        cases_json JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (company_id, agent_id)
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.eval_postgres_schema}.agent_eval_runs (
                        id BIGSERIAL PRIMARY KEY,
                        run_id TEXT NOT NULL UNIQUE,
                        company_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        rag_backend TEXT NOT NULL,
                        payload_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_agent_eval_runs_company_agent_created
                    ON {self.eval_postgres_schema}.agent_eval_runs (company_id, agent_id, created_at DESC)
                    """
                )

    def create_agent(
        self,
        org_id: str,
        company_id: str,
        name: str,
        objective: str,
        tone: str,
        description: str,
        rag_backend: str,
        generation_provider: str,
        use_openai_generation: bool,
        openai_model: str,
    ) -> AgentRecord:
        clean_name = name.strip()
        if len(clean_name) < 2:
            raise AgentValidationError("El nombre del agente debe tener al menos 2 caracteres")

        backend = _normalize_rag_backend(rag_backend)

        provider = generation_provider.strip().lower()
        if provider not in SUPPORTED_GENERATION_PROVIDERS:
            raise AgentValidationError("generation_provider invalido")

        scaffold_agent_id = Path(company_id).name
        if not scaffold_agent_id:
            raise AgentValidationError("company_id invalido")

        created = self.repository.create_agent(
            org_id=org_id,
            company_id=company_id,
            name=clean_name,
            objective=objective.strip() or "Responder consultas de la empresa",
            tone=tone.strip() or "profesional",
            description=description.strip(),
            rag_backend=backend,
            generation_provider=provider,
            use_openai_generation=use_openai_generation,
            openai_model=openai_model.strip() or "gpt-4o-mini",
            knowledge_dir="",
            index_path="",
        )

        agent_root = self.knowledge_root / created.agent_id
        company_root = agent_root / company_id
        company_root.mkdir(parents=True, exist_ok=True)
        sync_shared_knowledge(agent_root=agent_root, company_id=company_id)
        index_path = self.index_root / f"{created.agent_id}.joblib"

        created.knowledge_dir = str(agent_root)
        created.index_path = str(index_path)
        return self.repository.update_agent(created)

    def list_agents(self, allowed_org_ids: set[str], company_id: str | None = None) -> list[AgentRecord]:
        return self.repository.list_agents(org_ids=allowed_org_ids, company_id=company_id)

    def get_accessible_agent(self, agent_id: str, allowed_org_ids: set[str]) -> AgentRecord:
        agent = self.repository.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError("Agente no encontrado")
        if agent.org_id not in allowed_org_ids:
            raise AgentForbiddenError("No tenes acceso a este agente")
        return agent

    def list_documents(self, agent_id: str) -> list[AgentDocumentRecord]:
        return self.repository.list_documents(agent_id)

    def get_whatsapp_channel_config(self, agent: AgentRecord) -> dict[str, str | None]:
        config_path = self._whatsapp_config_path(agent)
        if not config_path.exists():
            return {
                "phone_number_id": None,
                "business_account_id": None,
                "verify_token": None,
                "updated_at": None,
            }

        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentValidationError("No se pudo leer configuracion de WhatsApp") from exc

        if not isinstance(payload, dict):
            raise AgentValidationError("Configuracion de WhatsApp invalida")

        return {
            "phone_number_id": str(payload.get("phone_number_id") or "").strip() or None,
            "business_account_id": str(payload.get("business_account_id") or "").strip() or None,
            "verify_token": str(payload.get("verify_token") or "").strip() or None,
            "updated_at": str(payload.get("updated_at") or "").strip() or None,
        }

    def update_whatsapp_channel_config(
        self,
        agent: AgentRecord,
        phone_number_id: str | None,
        business_account_id: str | None,
        verify_token: str | None,
    ) -> dict[str, str | None]:
        clean_phone_number_id = (phone_number_id or "").strip()
        clean_business_account_id = (business_account_id or "").strip()
        clean_verify_token = (verify_token or "").strip()

        if clean_phone_number_id and len(clean_phone_number_id) < 6:
            raise AgentValidationError("phone_number_id invalido")
        if clean_business_account_id and len(clean_business_account_id) < 6:
            raise AgentValidationError("business_account_id invalido")
        if clean_verify_token and len(clean_verify_token) < 6:
            raise AgentValidationError("verify_token invalido")

        payload = {
            "phone_number_id": clean_phone_number_id or None,
            "business_account_id": clean_business_account_id or None,
            "verify_token": clean_verify_token or None,
            "updated_at": datetime.now(UTC).isoformat(),
        }

        config_path = self._whatsapp_config_path(agent)
        try:
            config_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        except OSError as exc:
            raise AgentValidationError("No se pudo guardar configuracion de WhatsApp") from exc

        return {
            "phone_number_id": payload["phone_number_id"],
            "business_account_id": payload["business_account_id"],
            "verify_token": payload["verify_token"],
            "updated_at": payload["updated_at"],
        }

    def _whatsapp_config_path(self, agent: AgentRecord) -> Path:
        company_root = Path(agent.knowledge_dir) / agent.company_id
        company_root.mkdir(parents=True, exist_ok=True)
        return company_root / "whatsapp.config.json"

    def list_rag_decision_history(self, agent: AgentRecord) -> list[dict[str, object]]:
        history_path = self._rag_decision_history_path(agent)
        if not history_path.exists():
            return []

        rows: list[dict[str, object]] = []
        try:
            for raw_line in history_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentValidationError("No se pudo leer historial de decisiones RAG") from exc

        return rows[-20:]

    def save_rag_decision(
        self,
        agent: AgentRecord,
        decision: str,
        current_backend: str,
        baseline_backend: str | None,
        reason: str,
        grounded_rate_delta: float | None,
        fallback_rate_delta: float | None,
        score_delta: float | None,
        latency_delta_ms: float | None,
    ) -> dict[str, object]:
        clean_decision = (decision or "").strip()
        clean_current = (current_backend or "").strip().lower()
        clean_baseline = (baseline_backend or "").strip().lower() or None
        clean_reason = (reason or "").strip()

        if len(clean_decision) < 2:
            raise AgentValidationError("decision invalida")
        if clean_current not in SUPPORTED_RAG_BACKENDS:
            raise AgentValidationError("current_backend invalido")
        if clean_baseline is not None and clean_baseline not in SUPPORTED_RAG_BACKENDS:
            raise AgentValidationError("baseline_backend invalido")
        if len(clean_reason) < 6:
            raise AgentValidationError("reason invalido")

        row = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "agent_id": agent.agent_id,
            "company_id": agent.company_id,
            "decision": clean_decision,
            "current_backend": clean_current,
            "baseline_backend": clean_baseline,
            "reason": clean_reason,
            "grounded_rate_delta": grounded_rate_delta,
            "fallback_rate_delta": fallback_rate_delta,
            "score_delta": score_delta,
            "latency_delta_ms": latency_delta_ms,
        }

        history_path = self._rag_decision_history_path(agent)
        try:
            with history_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=True))
                handle.write("\n")
        except OSError as exc:
            raise AgentValidationError("No se pudo guardar decision RAG") from exc

        return row

    def _rag_decision_history_path(self, agent: AgentRecord) -> Path:
        company_root = Path(agent.knowledge_dir) / agent.company_id
        company_root.mkdir(parents=True, exist_ok=True)
        return company_root / "rag.decisions.jsonl"

    def get_evaluation_dataset(self, agent: AgentRecord) -> list[dict[str, str]]:
        if self.eval_storage_backend == "postgres":
            with self._eval_pg_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        (
                            f"SELECT cases_json FROM {self.eval_postgres_schema}.agent_eval_datasets "
                            "WHERE company_id = %s AND agent_id = %s"
                        ),
                        (agent.company_id, agent.agent_id),
                    )
                    row = cur.fetchone()
                    payload = row[0] if row else []

            if not isinstance(payload, list):
                raise AgentValidationError("Dataset de evaluacion invalido")

            rows: list[dict[str, str]] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question") or "").strip()
                expected_answer = str(item.get("expected_answer") or "").strip()
                if not question or not expected_answer:
                    continue
                rows.append({"question": question, "expected_answer": expected_answer})
            return rows

        path = self._evaluation_dataset_path(agent)
        if not path.exists():
            return []

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentValidationError("No se pudo leer dataset de evaluacion") from exc

        if not isinstance(payload, list):
            raise AgentValidationError("Dataset de evaluacion invalido")

        rows: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "").strip()
            expected_answer = str(item.get("expected_answer") or "").strip()
            if not question or not expected_answer:
                continue
            rows.append({"question": question, "expected_answer": expected_answer})
        return rows

    def save_evaluation_dataset(self, agent: AgentRecord, cases: list[dict[str, str]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in cases:
            question = str(item.get("question") or "").strip()
            expected_answer = str(item.get("expected_answer") or "").strip()
            if len(question) < 5 or len(expected_answer) < 5:
                continue
            normalized.append({"question": question, "expected_answer": expected_answer})

        if len(normalized) < 5:
            raise AgentValidationError("El dataset de evaluacion debe tener al menos 5 casos validos")

        if self.eval_storage_backend == "postgres":
            with self._eval_pg_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        (
                            f"""
                            INSERT INTO {self.eval_postgres_schema}.agent_eval_datasets
                            (company_id, agent_id, cases_json, updated_at)
                            VALUES (%s, %s, %s::jsonb, NOW())
                            ON CONFLICT (company_id, agent_id)
                            DO UPDATE SET
                                cases_json = EXCLUDED.cases_json,
                                updated_at = NOW()
                            """
                        ),
                        (agent.company_id, agent.agent_id, json.dumps(normalized, ensure_ascii=True)),
                    )
            return normalized

        path = self._evaluation_dataset_path(agent)
        try:
            path.write_text(json.dumps(normalized, ensure_ascii=True, indent=2), encoding="utf-8")
        except OSError as exc:
            raise AgentValidationError("No se pudo guardar dataset de evaluacion") from exc

        return normalized

    def run_evaluation(self, agent: AgentRecord, sample_size: int | None = None) -> dict[str, object]:
        dataset = self.get_evaluation_dataset(agent)
        if not dataset:
            raise AgentValidationError("No hay dataset de evaluacion para este agente")

        selected = dataset
        if sample_size is not None and sample_size > 0:
            selected = dataset[: min(sample_size, len(dataset))]

        run_id = f"eval-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
        total = len(selected)
        correct = 0
        with_sources = 0
        fallback_count = 0
        score_sum = 0.0
        semantic_score_sum = 0.0
        semantic_scored_cases = 0
        semantic_correct = 0
        latencies_ms: list[int] = []
        judge_enabled = os.getenv("EVAL_LLM_JUDGE_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        for index, item in enumerate(selected):
            question = item["question"]
            expected_answer = item["expected_answer"]
            started = time.perf_counter()
            response = self.chat(
                agent=agent,
                message=question,
                company_id=agent.company_id,
                top_k=4,
                session_id=f"{run_id}-case-{index}",
                use_openai=False,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            latencies_ms.append(latency_ms)

            if response.sources:
                with_sources += 1
            if response.fallback_applied:
                fallback_count += 1

            expected_terms = [
                token
                for token in re.split(r"[^a-zA-Z0-9]+", expected_answer.lower())
                if len(token) >= 4
            ][:12]
            answer_lower = response.answer.lower()

            if expected_terms:
                matches = len([token for token in expected_terms if token in answer_lower])
                case_score = matches / len(expected_terms)
            else:
                case_score = 0.0

            score_sum += case_score
            if case_score >= 0.35:
                correct += 1

            if judge_enabled:
                semantic_score = self._semantic_case_score(
                    question=question,
                    expected_answer=expected_answer,
                    actual_answer=response.answer,
                )
                if semantic_score is not None:
                    semantic_scored_cases += 1
                    semantic_score_sum += semantic_score
                    if semantic_score >= 0.6:
                        semantic_correct += 1

        avg_latency = sum(latencies_ms) / max(len(latencies_ms), 1)
        semantic_score_avg = (
            semantic_score_sum / semantic_scored_cases if semantic_scored_cases > 0 else None
        )
        semantic_accuracy = (
            semantic_correct / semantic_scored_cases if semantic_scored_cases > 0 else None
        )
        run = {
            "run_id": run_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            "agent_id": agent.agent_id,
            "company_id": agent.company_id,
            "rag_backend": agent.rag_backend,
            "cases_total": total,
            "accuracy": round(correct / max(total, 1), 6),
            "semantic_accuracy": round(semantic_accuracy, 6) if semantic_accuracy is not None else None,
            "grounded_rate": round(with_sources / max(total, 1), 6),
            "fallback_rate": round(fallback_count / max(total, 1), 6),
            "avg_case_score": round(score_sum / max(total, 1), 6),
            "semantic_score_avg": round(semantic_score_avg, 6) if semantic_score_avg is not None else None,
            "avg_latency_ms": round(avg_latency, 2),
            "llm_judge_enabled": judge_enabled,
            "llm_judge_scored_cases": semantic_scored_cases,
        }

        self._append_evaluation_run(agent, run)
        return run

    def list_evaluation_runs(self, agent: AgentRecord, limit: int = 20) -> list[dict[str, object]]:
        if self.eval_storage_backend == "postgres":
            with self._eval_pg_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        (
                            f"""
                            SELECT payload_json
                            FROM {self.eval_postgres_schema}.agent_eval_runs
                            WHERE company_id = %s AND agent_id = %s
                            ORDER BY created_at DESC
                            LIMIT %s
                            """
                        ),
                        (agent.company_id, agent.agent_id, max(1, limit)),
                    )
                    rows = cur.fetchall()

            output: list[dict[str, object]] = []
            for row in reversed(rows):
                payload = row[0]
                if isinstance(payload, dict):
                    output.append(payload)
            return output

        path = self._evaluation_runs_path(agent)
        if not path.exists():
            return []

        rows: list[dict[str, object]] = []
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentValidationError("No se pudo leer historial de evaluacion") from exc

        return rows[-max(1, limit) :]

    def compare_latest_evaluation_runs(self, agent: AgentRecord) -> dict[str, object]:
        rows = self.list_evaluation_runs(agent, limit=2)
        current = rows[-1] if rows else None
        baseline = rows[-2] if len(rows) > 1 else None

        if current is None:
            return {
                "agent_id": agent.agent_id,
                "company_id": agent.company_id,
                "current": None,
                "baseline": None,
                "accuracy_delta": None,
                "semantic_accuracy_delta": None,
                "grounded_rate_delta": None,
                "fallback_rate_delta": None,
                "avg_case_score_delta": None,
                "semantic_score_avg_delta": None,
                "avg_latency_ms_delta": None,
            }

        if baseline is None:
            return {
                "agent_id": agent.agent_id,
                "company_id": agent.company_id,
                "current": current,
                "baseline": None,
                "accuracy_delta": None,
                "semantic_accuracy_delta": None,
                "grounded_rate_delta": None,
                "fallback_rate_delta": None,
                "avg_case_score_delta": None,
                "semantic_score_avg_delta": None,
                "avg_latency_ms_delta": None,
            }

        def _delta(key: str) -> float | None:
            current_value = current.get(key)
            baseline_value = baseline.get(key)
            if current_value is None or baseline_value is None:
                return None
            return round(float(current_value) - float(baseline_value), 6)

        return {
            "agent_id": agent.agent_id,
            "company_id": agent.company_id,
            "current": current,
            "baseline": baseline,
            "accuracy_delta": _delta("accuracy"),
            "semantic_accuracy_delta": _delta("semantic_accuracy"),
            "grounded_rate_delta": _delta("grounded_rate"),
            "fallback_rate_delta": _delta("fallback_rate"),
            "avg_case_score_delta": _delta("avg_case_score"),
            "semantic_score_avg_delta": _delta("semantic_score_avg"),
            "avg_latency_ms_delta": round(
                float(current.get("avg_latency_ms", 0.0)) - float(baseline.get("avg_latency_ms", 0.0)),
                2,
            ),
        }

    def _append_evaluation_run(self, agent: AgentRecord, run: dict[str, object]) -> None:
        if self.eval_storage_backend == "postgres":
            with self._eval_pg_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        (
                            f"""
                            INSERT INTO {self.eval_postgres_schema}.agent_eval_runs
                            (run_id, company_id, agent_id, rag_backend, payload_json)
                            VALUES (%s, %s, %s, %s, %s::jsonb)
                            """
                        ),
                        (
                            str(run.get("run_id") or ""),
                            agent.company_id,
                            agent.agent_id,
                            str(run.get("rag_backend") or agent.rag_backend),
                            json.dumps(run, ensure_ascii=True),
                        ),
                    )
            return

        path = self._evaluation_runs_path(agent)
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(run, ensure_ascii=True))
                handle.write("\n")
        except OSError as exc:
            raise AgentValidationError("No se pudo guardar corrida de evaluacion") from exc

    def _evaluation_dataset_path(self, agent: AgentRecord) -> Path:
        company_root = Path(agent.knowledge_dir) / agent.company_id
        company_root.mkdir(parents=True, exist_ok=True)
        return company_root / "rag.eval.dataset.json"

    def _evaluation_runs_path(self, agent: AgentRecord) -> Path:
        company_root = Path(agent.knowledge_dir) / agent.company_id
        company_root.mkdir(parents=True, exist_ok=True)
        return company_root / "rag.eval.runs.jsonl"

    def _semantic_case_score(
        self,
        question: str,
        expected_answer: str,
        actual_answer: str,
    ) -> float | None:
        api_key = self._resolve_eval_judge_api_key()
        if not api_key:
            return None

        model = os.getenv("EVAL_JUDGE_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        prompt = (
            "Evalua si la respuesta del asistente cubre semantica y factualmente la respuesta esperada. "
            "Responde SOLO JSON con clave score (float 0 a 1).\n"
            f"Pregunta: {question}\n"
            f"Esperado: {expected_answer}\n"
            f"Actual: {actual_answer}\n"
        )
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "Eres un evaluador estricto de calidad de respuestas."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        req = urllib_request.Request(
            url="https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

        try:
            with urllib_request.urlopen(req, timeout=25) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (urllib_error.URLError, urllib_error.HTTPError, json.JSONDecodeError):
            return None

        choices = raw.get("choices", []) if isinstance(raw, dict) else []
        if not choices:
            return None
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content", "") if isinstance(message, dict) else ""
        if not isinstance(content, str) or not content.strip():
            return None

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None

        score = parsed.get("score") if isinstance(parsed, dict) else None
        if score is None:
            return None
        try:
            numeric = float(score)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _resolve_eval_judge_api_key() -> str | None:
        key = os.getenv("EVAL_JUDGE_OPENAI_API_KEY", "").strip()
        if key:
            return key
        fallback = os.getenv("OPENAI_API_KEY", "").strip()
        return fallback or None

    def read_document_text(self, agent: AgentRecord, document_id: str) -> tuple[AgentDocumentRecord, str]:
        documents = self.repository.list_documents(agent.agent_id)
        document = next((item for item in documents if item.document_id == document_id), None)
        if document is None:
            raise AgentDocumentNotFoundError("Documento no encontrado")

        try:
            content = self.document_storage.read(document)
            text = load_text_content(document.filename, content)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise AgentValidationError("No se pudo leer el contenido del documento") from exc

        if not text.strip():
            raise AgentValidationError("El documento no contiene texto util")

        return document, text

    def delete_document(self, agent: AgentRecord, document_id: str) -> AgentDocumentRecord:
        document = self.repository.delete_document(agent.agent_id, document_id)
        if document is None:
            raise AgentDocumentNotFoundError("Documento no encontrado")

        try:
            self.document_storage.delete(document)
        except (FileNotFoundError, RuntimeError):
            logger.warning(
                "agent_document_delete_storage_skip agent_id=%s document_id=%s provider=%s",
                agent.agent_id,
                document.document_id,
                document.storage_provider,
            )

        return document

    def delete_agent(self, agent: AgentRecord) -> AgentRecord:
        documents = self.repository.list_documents(agent.agent_id)
        for document in documents:
            try:
                self.document_storage.delete(document)
            except (FileNotFoundError, RuntimeError):
                logger.warning(
                    "agent_delete_storage_skip agent_id=%s document_id=%s provider=%s",
                    agent.agent_id,
                    document.document_id,
                    document.storage_provider,
                )

        removed = self.repository.delete_agent(agent.agent_id)
        if removed is None:
            raise AgentNotFoundError("Agente no encontrado")

        for target_path in [
            Path(agent.knowledge_dir),
            Path(agent.index_path),
        ]:
            try:
                if target_path.is_dir():
                    shutil.rmtree(target_path, ignore_errors=True)
                elif target_path.exists():
                    target_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "agent_delete_cleanup_skip agent_id=%s path=%s",
                    agent.agent_id,
                    target_path,
                )

        return removed

    def update_agent(
        self,
        agent: AgentRecord,
        name: str | None = None,
        objective: str | None = None,
        tone: str | None = None,
        description: str | None = None,
        rag_backend: str | None = None,
        generation_provider: str | None = None,
        use_openai_generation: bool | None = None,
        openai_model: str | None = None,
    ) -> AgentRecord:
        if name is not None:
            clean_name = name.strip()
            if len(clean_name) < 2:
                raise AgentValidationError("El nombre del agente debe tener al menos 2 caracteres")
            agent.name = clean_name

        if objective is not None:
            clean_objective = objective.strip()
            if len(clean_objective) < 8:
                raise AgentValidationError("El objetivo debe tener al menos 8 caracteres")
            agent.objective = clean_objective

        if tone is not None:
            clean_tone = tone.strip()
            if len(clean_tone) < 3:
                raise AgentValidationError("El tono debe tener al menos 3 caracteres")
            agent.tone = clean_tone

        if description is not None:
            agent.description = description.strip()

        if rag_backend is not None:
            backend = _normalize_rag_backend(rag_backend)
            agent.rag_backend = backend

        if generation_provider is not None:
            provider = generation_provider.strip().lower()
            if provider not in SUPPORTED_GENERATION_PROVIDERS:
                raise AgentValidationError("generation_provider invalido")
            agent.generation_provider = provider

        if use_openai_generation is not None:
            agent.use_openai_generation = use_openai_generation

        if openai_model is not None:
            clean_model = openai_model.strip()
            if len(clean_model) < 3:
                raise AgentValidationError("openai_model invalido")
            agent.openai_model = clean_model

        return self.repository.update_agent(agent)

    def save_document(
        self,
        agent: AgentRecord,
        filename: str,
        content: bytes,
        operational_section: str | None = None,
    ) -> AgentDocumentRecord:
        clean_name = (filename or "").strip()
        if not clean_name:
            raise AgentValidationError("El archivo debe tener nombre")

        clean_section: str | None = None
        if operational_section is not None:
            candidate = operational_section.strip().lower()
            if candidate:
                if candidate not in SUPPORTED_OPERATIONAL_SECTIONS:
                    raise AgentValidationError("operational_section invalido")
                clean_section = candidate

        extension = Path(clean_name).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise AgentValidationError(
                "Formato no soportado. Usa txt, md, csv, json, pdf o docx"
            )
        if not content:
            raise AgentValidationError("El archivo esta vacio")

        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(clean_name).name).strip("-")
        if not safe_name:
            safe_name = f"documento{extension}"

        content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        checksum_sha256 = hashlib.sha256(content).hexdigest()
        learning_summary = self._build_generic_learning_summary(
            filename=safe_name,
            content=content,
            operational_section=clean_section,
        )
        stored = self.document_storage.save(
            agent=agent,
            filename=safe_name,
            content=content,
            content_type=content_type,
        )

        created = self.repository.add_document(
            agent_id=agent.agent_id,
            filename=safe_name,
            stored_path=stored.key,
            size_bytes=len(content),
            storage_provider=stored.provider,
            storage_key=stored.key,
            content_type=content_type,
            checksum_sha256=checksum_sha256,
            operational_section=clean_section,
            learning_summary=learning_summary,
        )

        self._remove_replaced_documents(
            agent=agent,
            current_document=created,
        )

        return created

    @staticmethod
    def _build_generic_learning_summary(
        filename: str,
        content: bytes,
        operational_section: str | None,
    ) -> str | None:
        try:
            text = load_text_content(filename, content)
        except (RuntimeError, ValueError):
            return None

        normalized = " ".join(text.split())
        if not normalized:
            return None

        sentences = [
            item.strip()
            for item in re.split(r"[.!?]\s+", normalized)
            if item.strip()
        ]
        excerpt = ". ".join(sentences[:2]).strip()
        if not excerpt:
            excerpt = normalized[:240].strip()

        word_count = len(normalized.split())
        section_label = operational_section or "general"
        return (
            f"Documento {filename} procesado para el bloque {section_label}. "
            f"Aprendizaje operativo: {excerpt}. "
            f"Cobertura aproximada: {word_count} palabras."
        )

    def _remove_replaced_documents(
        self,
        agent: AgentRecord,
        current_document: AgentDocumentRecord,
    ) -> None:
        existing_documents = self.repository.list_documents(agent.agent_id)
        current_canonical_name = _canonical_document_filename(current_document.filename)
        to_replace = [
            document
            for document in existing_documents
            if document.document_id != current_document.document_id
            and (
                document.filename == current_document.filename
                or _canonical_document_filename(document.filename) == current_canonical_name
                or (
                    bool(document.checksum_sha256)
                    and bool(current_document.checksum_sha256)
                    and document.checksum_sha256 == current_document.checksum_sha256
                )
            )
        ]

        if not to_replace:
            return

        for document in to_replace:
            removed = self.repository.delete_document(agent.agent_id, document.document_id)
            if removed is None:
                continue

            try:
                self.document_storage.delete(removed)
            except (FileNotFoundError, RuntimeError):
                logger.warning(
                    "agent_document_replace_storage_skip agent_id=%s document_id=%s provider=%s",
                    agent.agent_id,
                    removed.document_id,
                    removed.storage_provider,
                )

        logger.info(
            (
                "agent_document_upsert_replace agent_id=%s company_id=%s "
                "filename=%s replaced=%s"
            ),
            agent.agent_id,
            agent.company_id,
            current_document.filename,
            len(to_replace),
        )

    def rebuild_index(self, agent: AgentRecord) -> IndexBuildResult:
        openai_api_key = self._tenant_openai_api_key(agent.company_id)
        logger.info(
            "agent_index_rebuild_start agent_id=%s company_id=%s backend=%s",
            agent.agent_id,
            agent.company_id,
            agent.rag_backend,
        )
        try:
            documents = self._load_agent_knowledge_documents(agent)
            if not documents:
                raise ValueError(
                    "No se encontraron documentos validos. "
                    "Subi archivos txt, md, csv o json y reintenta"
                )

            chunks = chunk_documents(documents)
            requested_backend = agent.rag_backend.strip().lower()
            auto_requested = requested_backend == "auto"
            selected_backend = requested_backend
            if selected_backend == "auto":
                key_available = bool(openai_api_key or os.getenv("OPENAI_API_KEY", ""))
                selected_backend = "dense_openai" if key_available else "tfidf"

            if selected_backend == "hybrid":
                try:
                    index = HybridVectorIndex.build(
                        chunks,
                        max_features=int(os.getenv("RAG_MAX_FEATURES", "20000")),
                        embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small"),
                        embedding_batch_size=int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "64")),
                        api_key=openai_api_key,
                    )
                except RuntimeError:
                    if not auto_requested:
                        raise
                    index = TfidfVectorIndex.build(
                        chunks,
                        max_features=int(os.getenv("RAG_MAX_FEATURES", "20000")),
                    )
                    selected_backend = "tfidf"
            elif selected_backend == "dense_openai":
                try:
                    index = DenseVectorIndex.build(
                        chunks,
                        embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small"),
                        batch_size=int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "64")),
                        api_key=openai_api_key,
                    )
                except RuntimeError:
                    if not auto_requested:
                        raise
                    index = TfidfVectorIndex.build(
                        chunks,
                        max_features=int(os.getenv("RAG_MAX_FEATURES", "20000")),
                    )
                    selected_backend = "tfidf"
            else:
                index = TfidfVectorIndex.build(
                    chunks,
                    max_features=int(os.getenv("RAG_MAX_FEATURES", "20000")),
                )

            saved_path = index.save(agent.index_path)
            result = IndexBuildResult(
                index_path=saved_path,
                total_documents=len(documents),
                total_chunks=len(chunks),
                companies=sorted({document.company_id for document in documents}),
                backend=selected_backend,
            )
        except Exception as exc:
            self.repository.mark_documents_failed(agent.agent_id, str(exc))
            logger.warning(
                "agent_index_rebuild_failed agent_id=%s company_id=%s detail=%s",
                agent.agent_id,
                agent.company_id,
                exc,
            )
            raise

        self.repository.mark_documents_indexed(agent.agent_id)
        agent.indexed_at = datetime.now(UTC)
        self.repository.update_agent(agent)
        logger.info(
            "agent_index_rebuild_ok agent_id=%s company_id=%s backend=%s chunks=%s",
            agent.agent_id,
            agent.company_id,
            result.backend,
            result.total_chunks,
        )
        return result

    def chat(
        self,
        agent: AgentRecord,
        message: str,
        company_id: str,
        top_k: int = 4,
        session_id: str | None = None,
        visitor_id: str | None = None,
        external_user_id: str | None = None,
        channel: str = "api",
        use_openai: bool | None = None,
        generation_provider: str | None = None,
        generation_model: str | None = None,
    ) -> RAGAnswer:
        sync_shared_knowledge(agent_root=Path(agent.knowledge_dir), company_id=agent.company_id)
        role_context = build_role_context(agent=agent, channel=channel)
        clean_session_id = (session_id or "").strip()
        history = self._session_history(
            company_id=company_id,
            agent_id=agent.agent_id,
            session_id=clean_session_id,
        )
        session_summary = self._session_summary(
            company_id=company_id,
            agent_id=agent.agent_id,
            session_id=clean_session_id,
        )
        contextual_query = self._build_query(
            message=message,
            history=history,
            summary=session_summary,
            runtime_context=role_context.runtime_context,
        )
        policy_key = None
        if self.conversation_policy is not None and clean_session_id:
            policy_key = ConversationKey(
                company_id=company_id,
                agent_id=agent.agent_id,
                session_id=clean_session_id,
            )
            policy_decision = self.conversation_policy.evaluate(
                key=policy_key,
                message=message,
                visitor_id=visitor_id,
                external_user_id=external_user_id,
            )
            if policy_decision.action != "proceed" and policy_decision.answer:
                logger.info(
                    (
                        "agent_chat_policy_short_circuit agent_id=%s company_id=%s "
                        "session_id=%s action=%s repeat_count=%s reason=%s"
                    ),
                    agent.agent_id,
                    company_id,
                    clean_session_id,
                    policy_decision.action,
                    policy_decision.repeat_count,
                    policy_decision.reason,
                )
                return RAGAnswer(
                    answer=policy_decision.answer,
                    company_id=company_id,
                    sources=[],
                    retrieved_chunks=[],
                    intent_label="policy",
                    route="policy",
                    route_reason=policy_decision.reason,
                    response_mode=policy_decision.action,
                )

        selected_openai = agent.use_openai_generation if use_openai is None else use_openai
        selected_provider = self._resolve_generation_provider(
            agent=agent,
            company_id=company_id,
            provider_override=generation_provider,
        )
        if selected_provider in {"openai", "anthropic"} and generation_model:
            selected_openai = True
        selected_model = self._resolve_openai_model(
            company_id=company_id,
            model_override=generation_model,
            agent_openai_model=agent.openai_model,
        )
        selected_anthropic_model = self._resolve_anthropic_model(
            company_id=company_id,
            provider=selected_provider,
            model_override=generation_model,
        )
        min_score = self._rag_min_score()
        openai_api_key = self._tenant_openai_api_key(company_id)
        anthropic_api_key = self._tenant_anthropic_api_key(company_id)
        logger.info(
            (
                "agent_chat_llm_context agent_id=%s company_id=%s provider=%s model=%s "
                "anthropic_model=%s use_llm=%s openai_key=%s anthropic_key=%s"
            ),
            agent.agent_id,
            company_id,
            selected_provider,
            selected_model,
            selected_anthropic_model,
            selected_openai,
            bool(openai_api_key),
            bool(anthropic_api_key),
        )

        documents = self.repository.list_documents(agent.agent_id)
        has_uploaded_documents = any(document.status == "uploaded" for document in documents)
        has_index_artifact = Path(agent.index_path).exists()
        has_available_documents = any(
            document.status in {"uploaded", "indexed"}
            for document in documents
        )
        if has_index_artifact and not has_available_documents:
            logger.info(
                "agent_chat_ignore_stale_index agent_id=%s company_id=%s reason=no_available_documents",
                agent.agent_id,
                company_id,
            )
            has_index_artifact = False
        if not has_index_artifact and has_available_documents:
            has_uploaded_documents = True
        remote_generator = build_remote_generator(
            model=selected_model,
            generation_provider=selected_provider,
            anthropic_model=selected_anthropic_model,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )
        logger.info(
            "agent_chat_llm_generator agent_id=%s company_id=%s available=%s",
            agent.agent_id,
            company_id,
            remote_generator is not None,
        )
        llm_available = remote_generator is not None

        decision = self.orchestrator.decide(
            message=message,
            has_uploaded_documents=has_uploaded_documents,
            has_index_artifact=has_index_artifact,
            llm_requested=selected_openai,
            llm_available=llm_available,
            generation_provider=selected_provider,
            generation_model=selected_model,
            anthropic_model=selected_anthropic_model,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )
        logger.info(
            (
                "agent_chat_start agent_id=%s company_id=%s use_llm=%s provider=%s "
                "model=%s top_k=%s uploaded_docs=%s"
            ),
            agent.agent_id,
            company_id,
            selected_openai,
            selected_provider,
            selected_model,
            top_k,
            has_uploaded_documents,
        )
        logger.info(
            "agent_chat_orchestrated agent_id=%s company_id=%s intent=%s route=%s reason=%s",
            agent.agent_id,
            company_id,
            decision.intent,
            decision.route,
            decision.reason,
        )

        result, mode = self._resolve_chat_response(
            decision=decision,
            agent=agent,
            message=message,
            contextual_query=contextual_query,
            company_id=company_id,
            top_k=top_k,
            min_score=min_score,
            use_openai=selected_openai,
            generation_provider=selected_provider,
            generation_model=selected_model,
            anthropic_model=selected_anthropic_model,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            role_context=role_context,
        )
        fallback_applied = mode.endswith("_general_fallback")
        result = replace(
            result,
            answer=enforce_channel_response_contract(
                result.answer,
                query=message,
                channel=role_context.channel,
            ),
            intent_label=decision.intent,
            route=decision.route,
            route_reason=decision.reason,
            response_mode=mode,
            fallback_applied=fallback_applied,
            retrieval_min_score=min_score,
        )
        logger.info(
            "agent_chat_ok agent_id=%s company_id=%s mode=%s sources=%s answer_chars=%s",
            agent.agent_id,
            company_id,
            mode,
            len(result.sources),
            len(result.answer),
        )

        if self.conversation_policy is not None and policy_key is not None:
            self.conversation_policy.register_response(
                key=policy_key,
                answer=result.answer,
                visitor_id=visitor_id,
                external_user_id=external_user_id,
            )

        if clean_session_id:
            self.update_session_summary(
                company_id=company_id,
                agent_id=agent.agent_id,
                session_id=clean_session_id,
                user_message=message,
                assistant_message=result.answer,
                intent_label=decision.intent,
                channel=channel,
                reminder_recipient=(clean_session_id if channel in {"whatsapp", "widget_whatsapp"} else None),
            )
            memory_session_id = self._memory_session_id(agent.agent_id, clean_session_id)
            self.session_store.append_user_message(
                company_id=company_id,
                session_id=memory_session_id,
                text=message,
            )
            self.session_store.append_assistant_message(
                company_id=company_id,
                session_id=memory_session_id,
                text=result.answer,
            )

        return result

    @staticmethod
    def _memory_session_id(agent_id: str, session_id: str) -> str:
        return f"{agent_id.strip()}:{session_id.strip()}"

    def _session_summary(
        self,
        company_id: str,
        agent_id: str,
        session_id: str,
    ) -> SessionSummary:
        if not session_id:
            return SessionSummary()
        memory_session_id = self._memory_session_id(agent_id, session_id)
        return self.session_store.get_summary(company_id=company_id, session_id=memory_session_id)

    def get_session_summary(self, company_id: str, agent_id: str, session_id: str) -> SessionSummary:
        return self._session_summary(company_id=company_id, agent_id=agent_id, session_id=session_id)

    def get_session_summary_text(self, company_id: str, agent_id: str, session_id: str) -> str:
        return _format_session_summary(
            self._session_summary(company_id=company_id, agent_id=agent_id, session_id=session_id)
        )

    def update_session_summary(
        self,
        *,
        company_id: str,
        agent_id: str,
        session_id: str,
        user_message: str | None = None,
        assistant_message: str | None = None,
        intent_label: str | None = None,
        tool_name: str | None = None,
        product_queries: list[str] | None = None,
        selected_products: list[str] | None = None,
        shipping_preference: str | None = None,
        payment_preference: str | None = None,
        pickup_location_label: str | None = None,
        delivery_address: str | None = None,
        delivery_address_confirmed: bool | None = None,
        invoice_type: str | None = None,
        invoice_rut: str | None = None,
        invoice_business_name: str | None = None,
        invoice_address: str | None = None,
        customer_authenticated: bool | None = None,
        order_reference: str | None = None,
        notes: str | None = None,
        workflow_stage: str | None = None,
        pending_next_step: str | None = None,
        awaiting_slot: str | None = None,
        checkout_stage: str | None = None,
        focused_product: str | None = None,
        cart_actions: list[dict[str, object]] | None = None,
        reset_workflow: bool = False,
        otp_email: str | None = None,
        authenticated_at: str | None = None,
        workflow_reset_started_at: str | None = None,
        workflow_timeout_sent_at: str | None = None,
        channel: str | None = None,
        reminder_recipient: str | None = None,
    ) -> None:
        clean_session_id = (session_id or "").strip()
        if not clean_session_id:
            return
        memory_session_id = self._memory_session_id(agent_id, clean_session_id)
        summary = self.session_store.get_summary(company_id=company_id, session_id=memory_session_id)

        if reset_workflow:
            summary.funnel_stage = "browsing"
            summary.checkout_stage = ""
            summary.pending_next_step = ""
            summary.awaiting_slot = ""
            summary.last_product_query = ""
            summary.selected_products = ""
            summary.focused_product = ""
            summary.cart_snapshot = ""
            summary.shipping_preference = ""
            summary.pickup_location_label = ""
            summary.delivery_address = ""
            summary.delivery_address_confirmed = False
            summary.payment_preference = ""
            summary.customer_authenticated = False
            summary.order_reference = ""
            summary.otp_email = ""
            summary.authenticated_at = ""
            summary.workflow_reset_started_at = ""
            summary.workflow_timeout_sent_at = ""

        explicit_workflow_stage = normalize_stage(workflow_stage) if workflow_stage else ""
        if user_message and user_message.strip():
            summary.user_goal = _normalize_summary_value(user_message, 180)
        if (intent_label or "").strip().lower() == "clear_cart":
            summary.selected_products = ""
            summary.focused_product = ""
            summary.cart_snapshot = ""
            summary.last_product_query = ""
            summary.pending_next_step = ""
        if tool_name and tool_name.strip():
            summary.last_tool = tool_name.strip()
            if tool_name.strip() == "clear_cart":
                summary.selected_products = ""
                summary.focused_product = ""
                summary.cart_snapshot = ""
                summary.last_product_query = ""
                summary.pending_next_step = ""
        if product_queries:
            clean_queries = [item.strip() for item in product_queries if item and item.strip()]
            if clean_queries:
                summary.last_product_query = _normalize_summary_value(", ".join(clean_queries), 180)
        if selected_products:
            clean_products = [item.strip() for item in selected_products if item and item.strip()]
            if clean_products:
                summary.selected_products = _normalize_summary_value(", ".join(clean_products), 220)
                if not focused_product:
                    summary.focused_product = _normalize_summary_value(clean_products[0], 160)
        if focused_product is not None:
            summary.focused_product = _normalize_summary_value(focused_product, 160) if focused_product.strip() else ""
        next_cart_snapshot = _apply_cart_actions_to_snapshot(summary.cart_snapshot, cart_actions)
        if next_cart_snapshot is not None:
            summary.cart_snapshot = next_cart_snapshot
        if shipping_preference and shipping_preference.strip():
            summary.shipping_preference = _normalize_summary_value(shipping_preference, 120)
        if pickup_location_label and pickup_location_label.strip():
            summary.pickup_location_label = _normalize_summary_value(pickup_location_label, 120)
        if delivery_address and delivery_address.strip():
            summary.delivery_address = _normalize_summary_value(delivery_address, 200)
        if delivery_address_confirmed is not None:
            summary.delivery_address_confirmed = bool(delivery_address_confirmed)
        if invoice_type and invoice_type.strip():
            summary.invoice_type = _normalize_summary_value(invoice_type, 80)
        if invoice_rut and invoice_rut.strip():
            summary.invoice_rut = _normalize_summary_value(invoice_rut, 80)
        if invoice_business_name and invoice_business_name.strip():
            summary.invoice_business_name = _normalize_summary_value(invoice_business_name, 120)
        if invoice_address and invoice_address.strip():
            summary.invoice_address = _normalize_summary_value(invoice_address, 200)
        if payment_preference and payment_preference.strip():
            summary.payment_preference = _normalize_summary_value(payment_preference, 120)
        if customer_authenticated is not None:
            summary.customer_authenticated = bool(customer_authenticated)
        if order_reference and order_reference.strip():
            summary.order_reference = order_reference.strip()
        if assistant_message and assistant_message.strip():
            summary.last_action = _normalize_summary_value(assistant_message, 180)
        if notes and notes.strip():
            summary.notes = _normalize_summary_value(notes, 180)
        if pending_next_step is not None:
            summary.pending_next_step = _normalize_summary_value(pending_next_step, 120) if pending_next_step.strip() else ""
        if awaiting_slot is not None:
            summary.awaiting_slot = _normalize_summary_value(awaiting_slot, 120) if awaiting_slot.strip() else ""
        if checkout_stage is not None:
            summary.checkout_stage = _normalize_summary_value(checkout_stage, 80) if checkout_stage.strip() else ""
        if otp_email is not None:
            summary.otp_email = _normalize_summary_value(otp_email, 120) if otp_email.strip() else ""
        if authenticated_at is not None:
            summary.authenticated_at = authenticated_at.strip() if authenticated_at.strip() else ""
        if workflow_reset_started_at is not None:
            summary.workflow_reset_started_at = workflow_reset_started_at.strip() if workflow_reset_started_at.strip() else ""
        if workflow_timeout_sent_at is not None:
            summary.workflow_timeout_sent_at = workflow_timeout_sent_at.strip() if workflow_timeout_sent_at.strip() else ""
        if channel is not None:
            summary.last_channel = channel.strip() if channel.strip() else ""
        if reminder_recipient is not None:
            summary.reminder_recipient = reminder_recipient.strip() if reminder_recipient.strip() else ""

        current_state = build_workflow_state(
            stage=summary.funnel_stage,
            checkout_stage=summary.checkout_stage,
            selected_products=summary.selected_products,
            shipping_preference=summary.shipping_preference,
            pickup_location_label=summary.pickup_location_label,
            delivery_address=summary.delivery_address,
            delivery_address_confirmed=summary.delivery_address_confirmed,
            payment_preference=summary.payment_preference,
            customer_authenticated=summary.customer_authenticated,
            order_reference=summary.order_reference,
        )
        transition = resolve_transition(
            current=current_state,
            intent_label=intent_label,
            tool_name=tool_name,
        )
        if explicit_workflow_stage:
            summary.funnel_stage = explicit_workflow_stage
        elif transition.allowed:
            summary.funnel_stage = transition.next_stage
        else:
            summary.funnel_stage = current_state.stage
            if transition.notes and not summary.notes:
                summary.notes = transition.notes

        summary.updated_at = datetime.now(UTC).isoformat()

        self.session_store.save_summary(
            company_id=company_id,
            session_id=memory_session_id,
            summary=summary,
        )

    def _session_history(
        self,
        company_id: str,
        agent_id: str,
        session_id: str,
    ) -> list[tuple[str, str]]:
        if not session_id or self.history_window <= 0:
            return []
        memory_session_id = self._memory_session_id(agent_id, session_id)
        turns = self.session_store.recent_turns(
            company_id=company_id,
            session_id=memory_session_id,
            limit=self.history_window,
        )
        return [(turn.role, turn.text) for turn in turns]

    @staticmethod
    def _build_query(
        message: str,
        history: list[tuple[str, str]],
        summary: SessionSummary | None = None,
        runtime_context: str | None = None,
    ) -> str:
        history_block = _format_history_for_query(history)
        summary_block = _summarize_history_for_query(history)
        persistent_summary_block = _format_session_summary(summary or SessionSummary())
        context_block = (runtime_context or "").strip()
        parts: list[str] = [
            "## Rol y contexto operativo",
            context_block or "Sin contexto operativo adicional.",
            "",
            "## Resumen persistente",
            persistent_summary_block or "Sin resumen persistente.",
            "",
            "## Resumen reciente",
            summary_block or "Sin resumen reciente.",
            "",
            "## Historial reciente",
            history_block or "Sin historial reciente.",
            "",
            "## Consulta actual",
            message,
        ]
        return "\n".join(parts)

    def _resolve_chat_response(
        self,
        decision: OrchestrationDecision,
        agent: AgentRecord,
        message: str,
        contextual_query: str,
        company_id: str,
        top_k: int,
        min_score: float,
        use_openai: bool,
        generation_provider: str,
        generation_model: str,
        anthropic_model: str,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
        role_context: RoleContext,
    ) -> tuple[RAGAnswer, str]:
        if decision.route == "greeting":
            result = self._empty_knowledge_answer(
                company_id=company_id,
                message=message,
                contextual_query=contextual_query,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=role_context.objective,
                tone=role_context.tone,
                system_rules=role_context.system_rules,
                allow_general_llm=True,
            )
            return result, "greeting"

        if decision.route == "general_llm":
            result = self._empty_knowledge_answer(
                company_id=company_id,
                message=message,
                contextual_query=contextual_query,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=role_context.objective,
                tone=role_context.tone,
                system_rules=role_context.system_rules,
                allow_general_llm=True,
            )
            return result, "general_llm"

        if decision.route == "no_knowledge":
            result = self._empty_knowledge_answer(
                company_id=company_id,
                message=message,
                contextual_query=contextual_query,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=role_context.objective,
                tone=role_context.tone,
                system_rules=role_context.system_rules,
                allow_general_llm=False,
            )
            return result, "no_knowledge"

        if decision.route == "rag_live_docs":
            primary = self._chat_with_live_documents(
                agent=agent,
                message=message,
                contextual_query=contextual_query,
                company_id=company_id,
                top_k=top_k,
                min_score=min_score,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=role_context.objective,
                tone=role_context.tone,
                system_rules=role_context.system_rules,
            )
            return self._apply_general_fallback_when_rag_has_no_evidence(
                primary_result=primary,
                primary_mode="live_docs",
                decision=decision,
                company_id=company_id,
                message=message,
                contextual_query=contextual_query,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=role_context.objective,
                tone=role_context.tone,
                system_rules=role_context.system_rules,
            )

        try:
            pipeline = RAGPipeline.from_artifact(
                index_path=agent.index_path,
                use_openai=use_openai,
                openai_model=generation_model,
                generation_provider=generation_provider,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
            )
            primary = pipeline.answer(
                query=contextual_query,
                company_id=company_id,
                top_k=top_k,
                min_score=min_score,
                objective=role_context.objective,
                tone=role_context.tone,
                system_rules=role_context.system_rules,
            )
            return self._apply_general_fallback_when_rag_has_no_evidence(
                primary_result=primary,
                primary_mode="index_artifact",
                decision=decision,
                company_id=company_id,
                message=message,
                contextual_query=contextual_query,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=role_context.objective,
                tone=role_context.tone,
                system_rules=role_context.system_rules,
            )
        except FileNotFoundError:
            logger.info(
                "agent_chat_fallback_live_docs agent_id=%s company_id=%s reason=missing_index",
                agent.agent_id,
                company_id,
            )
            primary = self._chat_with_live_documents(
                company_id=company_id,
                agent=agent,
                message=message,
                contextual_query=contextual_query,
                top_k=top_k,
                min_score=min_score,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=role_context.objective,
                tone=role_context.tone,
                system_rules=role_context.system_rules,
            )
            return self._apply_general_fallback_when_rag_has_no_evidence(
                primary_result=primary,
                primary_mode="missing_index_fallback",
                decision=decision,
                company_id=company_id,
                message=message,
                contextual_query=contextual_query,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=role_context.objective,
                tone=role_context.tone,
                system_rules=role_context.system_rules,
            )

    @staticmethod
    def _apply_general_fallback_when_rag_has_no_evidence(
        primary_result: RAGAnswer,
        primary_mode: str,
        decision: OrchestrationDecision,
        company_id: str,
        message: str,
        contextual_query: str,
        use_openai: bool,
        generation_provider: str,
        generation_model: str,
        anthropic_model: str,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
        objective: str | None,
        tone: str | None,
        system_rules: str | None,
    ) -> tuple[RAGAnswer, str]:
        if primary_result.sources:
            return primary_result, primary_mode
        if decision.intent == "company_specific":
            return primary_result, primary_mode

        fallback = AgentService._empty_knowledge_answer(
            company_id=company_id,
            message=message,
            contextual_query=contextual_query,
            use_openai=use_openai,
            generation_provider=generation_provider,
            generation_model=generation_model,
            anthropic_model=anthropic_model,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            objective=objective,
            tone=tone,
            system_rules=system_rules,
            allow_general_llm=True,
        )
        return fallback, f"{primary_mode}_general_fallback"

    def _chat_with_live_documents(
        self,
        agent: AgentRecord,
        message: str,
        contextual_query: str,
        company_id: str,
        top_k: int,
        min_score: float,
        use_openai: bool,
        generation_provider: str,
        generation_model: str,
        anthropic_model: str,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
        objective: str | None,
        tone: str | None,
        system_rules: str | None,
    ) -> RAGAnswer:
        documents = self._load_agent_knowledge_documents(agent)

        company_documents = [document for document in documents if document.company_id == company_id]
        if not company_documents:
            return self._empty_knowledge_answer(
                company_id=company_id,
                message=message,
                contextual_query=contextual_query,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=objective,
                tone=tone,
                system_rules=system_rules,
                allow_general_llm=False,
            )

        try:
            chunks = chunk_documents(company_documents)
        except ValueError:
            return self._empty_knowledge_answer(
                company_id=company_id,
                message=message,
                contextual_query=contextual_query,
                use_openai=use_openai,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                objective=objective,
                tone=tone,
                system_rules=system_rules,
                allow_general_llm=False,
            )

        index = TfidfVectorIndex.build(chunks)
        retrieved_chunks = index.search(
            query=contextual_query,
            company_id=company_id,
            top_k=top_k,
            min_score=min_score,
        )

        remote_generator = build_remote_generator(
            model=generation_model,
            generation_provider=generation_provider,
            anthropic_model=anthropic_model,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )

        if use_openai and remote_generator is not None:
            try:
                answer_text = remote_generator.generate(
                    query=contextual_query,
                    chunks=retrieved_chunks,
                    objective=objective,
                    tone=tone,
                    system_rules=system_rules,
                )
            except RuntimeError as exc:
                logger.warning(
                    (
                        "agent_chat_llm_generation_failed agent_id=%s company_id=%s "
                        "provider=%s model=%s detail=%s"
                    ),
                    agent.agent_id,
                    company_id,
                    generation_provider,
                    generation_model,
                    exc,
                )
                fallback_generator = ExtractiveAnswerGenerator(
                    openai_requested=False,
                    openai_available=False,
                )
                fallback_answer = fallback_generator.generate(
                    query=contextual_query,
                    chunks=retrieved_chunks,
                    objective=objective,
                    tone=tone,
                    system_rules=system_rules,
                )
                answer_text = (
                    "Nota: el proveedor LLM no estuvo disponible temporalmente, respondo en modo "
                    "extractivo con evidencia.\n"
                    f"{fallback_answer}"
                )
        else:
            answer_text = ExtractiveAnswerGenerator(
                openai_requested=use_openai,
                openai_available=remote_generator is not None,
            ).generate(
                query=contextual_query,
                chunks=retrieved_chunks,
                objective=objective,
                tone=tone,
                system_rules=system_rules,
            )

        sources = sorted({chunk.source for chunk in retrieved_chunks})
        answer_text = tune_answer_style(answer_text, query=message)
        return RAGAnswer(
            answer=answer_text,
            company_id=company_id,
            sources=sources,
            retrieved_chunks=retrieved_chunks,
        )

    def _load_agent_knowledge_documents(self, agent: AgentRecord) -> list[KnowledgeDocument]:
        sync_shared_knowledge(agent_root=Path(agent.knowledge_dir), company_id=agent.company_id)
        documents = self.repository.list_documents(agent.agent_id)
        knowledge_documents: list[KnowledgeDocument] = []

        for document in documents:
            if document.status == "failed":
                continue

            try:
                content = self.document_storage.read(document)
                text = load_text_content(document.filename, content)
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                logger.warning(
                    (
                        "agent_document_load_failed agent_id=%s document_id=%s "
                        "provider=%s detail=%s"
                    ),
                    agent.agent_id,
                    document.document_id,
                    document.storage_provider,
                    exc,
                )
                continue

            if not text:
                continue

            source = document.filename
            metadata = {
                "extension": Path(document.filename).suffix.lower(),
                "filename": document.filename,
                "document_id": document.document_id,
                "storage_provider": document.storage_provider,
            }
            knowledge_documents.append(
                KnowledgeDocument(
                    company_id=agent.company_id,
                    source=source,
                    text=text,
                    metadata=metadata,
                )
            )

        return knowledge_documents

    @staticmethod
    def _empty_knowledge_answer(
        company_id: str,
        message: str,
        contextual_query: str,
        use_openai: bool,
        generation_provider: str,
        generation_model: str,
        anthropic_model: str,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
        objective: str | None,
        tone: str | None,
        system_rules: str | None,
        allow_general_llm: bool,
    ) -> RAGAnswer:
        remote_generator = build_remote_generator(
            model=generation_model,
            generation_provider=generation_provider,
            anthropic_model=anthropic_model,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )

        if allow_general_llm and use_openai and remote_generator is not None:
            try:
                answer_text = remote_generator.generate(
                    query=contextual_query,
                    chunks=[],
                    objective=objective,
                    tone=tone,
                    system_rules=system_rules,
                )
            except RuntimeError as exc:
                logger.warning(
                    (
                        "agent_general_llm_generation_failed company_id=%s "
                        "provider=%s model=%s detail=%s"
                    ),
                    company_id,
                    generation_provider,
                    generation_model,
                    exc,
                )
                answer_text = ExtractiveAnswerGenerator(
                    openai_requested=use_openai,
                    openai_available=False,
                ).generate(
                    query=contextual_query,
                    chunks=[],
                    objective=objective,
                    tone=tone,
                    system_rules=system_rules,
                )
        else:
            answer_text = ExtractiveAnswerGenerator(
                openai_requested=use_openai,
                openai_available=remote_generator is not None,
            ).generate(
                query=contextual_query,
                chunks=[],
                objective=objective,
                tone=tone,
                system_rules=system_rules,
            )

        return RAGAnswer(
            answer=tune_answer_style(answer_text, query=message),
            company_id=company_id,
            sources=[],
            retrieved_chunks=[],
        )

    @staticmethod
    def _greeting_answer(company_id: str) -> RAGAnswer:
        return RAGAnswer(
            answer=(
                "Hola! Como va? Te puedo ayudar con consultas generales o con informacion de tu empresa. "
                "Si queres respuestas especificas de la empresa, subi documentos al conocimiento y las respondo con evidencia."
            ),
            company_id=company_id,
            sources=[],
            retrieved_chunks=[],
        )

    @staticmethod
    def _rag_min_score() -> float:
        raw_value = os.getenv("AGENT_RAG_MIN_SCORE", os.getenv("RAG_MIN_SCORE", "0.08"))
        try:
            parsed = float(raw_value)
        except ValueError:
            return 0.08
        return max(0.0, min(1.0, parsed))

    def _tenant_openai_api_key(self, company_id: str) -> str | None:
        if self.llm_settings_service is None:
            return None
        settings = self.llm_settings_service.get(company_id)
        return settings.openai_api_key or None

    def _tenant_anthropic_api_key(self, company_id: str) -> str | None:
        if self.llm_settings_service is None:
            return None
        settings = self.llm_settings_service.get(company_id)
        return settings.anthropic_api_key or None

    def _resolve_generation_provider(
        self,
        agent: AgentRecord,
        company_id: str,
        provider_override: str | None,
    ) -> str:
        if provider_override is not None:
            candidate = provider_override.strip().lower()
            if candidate in SUPPORTED_GENERATION_PROVIDERS:
                return candidate

        if self.llm_settings_service is not None:
            tenant_settings = self.llm_settings_service.get(company_id)
            if tenant_settings.generation_provider in {"openai", "anthropic"}:
                return tenant_settings.generation_provider

        if agent.generation_provider in {"openai", "anthropic"}:
            return agent.generation_provider

        env_provider = os.getenv("RAG_GENERATION_PROVIDER", "auto").strip().lower()
        if env_provider in {"openai", "anthropic"}:
            return env_provider
        return "auto"

    def _resolve_openai_model(
        self,
        company_id: str,
        model_override: str | None,
        agent_openai_model: str,
    ) -> str:
        if model_override and model_override.strip():
            return model_override.strip()

        if self.llm_settings_service is not None:
            tenant_settings = self.llm_settings_service.get(company_id)
            if tenant_settings.openai_model.strip():
                return tenant_settings.openai_model.strip()

        if agent_openai_model.strip():
            return agent_openai_model.strip()

        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _resolve_anthropic_model(
        self,
        company_id: str,
        provider: str,
        model_override: str | None,
    ) -> str:
        if model_override and provider == "anthropic":
            return model_override.strip()

        if self.llm_settings_service is not None:
            tenant_settings = self.llm_settings_service.get(company_id)
            if tenant_settings.anthropic_model.strip():
                return tenant_settings.anthropic_model.strip()

        return os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
