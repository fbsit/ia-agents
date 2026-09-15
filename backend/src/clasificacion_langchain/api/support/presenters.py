from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from clasificacion_langchain.api.schemas import (
    AgentDocumentContentPayload,
    AgentDocumentPayload,
    AgentFeedbackSummaryPayload,
    AgentPayload,
    AgentWhatsAppConfigPayload,
    ChatAuditCostRowPayload,
    ChatAuditSummaryRowPayload,
    EvaluationComparePayload,
    EvaluationRunJobPayload,
    EvaluationRunPayload,
    RagDecisionRecordPayload,
    RetrievalBackendMetricsPayload,
    RetrievalComparisonPayload,
    RetrievalAuditSummaryRowPayload,
    TenantLlmSettingsPayload,
)
from clasificacion_langchain.analytics.chat_audit import ChatAuditCostRow, ChatAuditSummaryRow
from clasificacion_langchain.analytics.feedback_audit import AgentFeedbackSummary
from clasificacion_langchain.analytics.retrieval_audit import (
    RetrievalBackendMetrics,
    RetrievalComparisonRow,
    RetrievalAuditSummaryRow,
)
from clasificacion_langchain.settings.service import TenantLlmSettings


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    if not authorization.lower().startswith("bearer "):
        return ""
    return authorization[7:].strip()


def membership_payload(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"org_id": item.get("org_id", ""), "role": item.get("role", "member")}
        for item in items
    ]


def to_agent_payload(agent, documents_count: int) -> AgentPayload:
    indexed_at = agent.indexed_at.isoformat() if agent.indexed_at else None
    return AgentPayload(
        agent_id=agent.agent_id,
        org_id=agent.org_id,
        company_id=agent.company_id,
        name=agent.name,
        objective=agent.objective,
        tone=agent.tone,
        description=agent.description,
        rag_backend=agent.rag_backend,
        generation_provider=agent.generation_provider,
        use_openai_generation=agent.use_openai_generation,
        openai_model=agent.openai_model,
        knowledge_dir=agent.knowledge_dir,
        index_path=agent.index_path,
        indexed_at=indexed_at,
        documents_count=documents_count,
    )


def mask_secret(secret: str) -> str | None:
    token = (secret or "").strip()
    if not token:
        return None
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def settings_payload(settings: TenantLlmSettings) -> TenantLlmSettingsPayload:
    env_openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    env_anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    has_tenant_openai_key = bool(settings.openai_api_key)
    has_tenant_anthropic_key = bool(settings.anthropic_api_key)
    has_openai_api_key = has_tenant_openai_key or bool(env_openai_key)
    has_anthropic_api_key = has_tenant_anthropic_key or bool(env_anthropic_key)
    openai_source = "tenant" if has_tenant_openai_key else "env" if env_openai_key else "none"
    anthropic_source = "tenant" if has_tenant_anthropic_key else "env" if env_anthropic_key else "none"
    openai_masked = mask_secret(settings.openai_api_key) or mask_secret(env_openai_key)
    anthropic_masked = mask_secret(settings.anthropic_api_key) or mask_secret(env_anthropic_key)
    return TenantLlmSettingsPayload(
        company_id=settings.company_id,
        generation_provider=settings.generation_provider,
        openai_model=settings.openai_model,
        anthropic_model=settings.anthropic_model,
        has_openai_api_key=has_openai_api_key,
        has_anthropic_api_key=has_anthropic_api_key,
        openai_api_key_masked=openai_masked,
        anthropic_api_key_masked=anthropic_masked,
        openai_key_source=openai_source,
        anthropic_key_source=anthropic_source,
        updated_at=settings.updated_at.isoformat(),
    )


def document_payload(document) -> AgentDocumentPayload:
    indexed_at = document.indexed_at.isoformat() if document.indexed_at else None
    summary_updated_at = document.summary_updated_at.isoformat() if document.summary_updated_at else None
    return AgentDocumentPayload(
        document_id=document.document_id,
        agent_id=document.agent_id,
        filename=document.filename,
        size_bytes=document.size_bytes,
        status=document.status,
        indexed_at=indexed_at,
        error_message=document.error_message,
        created_at=document.created_at.isoformat(),
        operational_section=document.operational_section,
        learning_summary=document.learning_summary,
        summary_updated_at=summary_updated_at,
    )


def document_content_payload(document, content: str) -> AgentDocumentContentPayload:
    return AgentDocumentContentPayload(
        document_id=document.document_id,
        agent_id=document.agent_id,
        filename=document.filename,
        status=document.status,
        created_at=document.created_at.isoformat(),
        content=content,
    )


def whatsapp_config_payload(*, agent_id: str, company_id: str, webhook_url: str, config: dict[str, str | None]) -> AgentWhatsAppConfigPayload:
    return AgentWhatsAppConfigPayload(
        agent_id=agent_id,
        company_id=company_id,
        webhook_url=webhook_url,
        phone_number_id=config.get("phone_number_id"),
        business_account_id=config.get("business_account_id"),
        verify_token=config.get("verify_token"),
        updated_at=config.get("updated_at"),
    )


def to_audit_summary_payload(row: ChatAuditSummaryRow) -> ChatAuditSummaryRowPayload:
    return ChatAuditSummaryRowPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        assistant_messages=row.assistant_messages,
        cached_responses=row.cached_responses,
        generic_repeat_responses=row.generic_repeat_responses,
        closed_conversations=row.closed_conversations,
    )


def to_audit_cost_payload(row: ChatAuditCostRow) -> ChatAuditCostRowPayload:
    return ChatAuditCostRowPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        assistant_messages=row.assistant_messages,
        llm_messages=row.llm_messages,
        avoided_llm_calls=row.avoided_llm_calls,
        estimated_spent_usd=row.estimated_spent_usd,
        estimated_saved_usd=row.estimated_saved_usd,
    )


def to_retrieval_summary_payload(row: RetrievalAuditSummaryRow) -> RetrievalAuditSummaryRowPayload:
    return RetrievalAuditSummaryRowPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        queries_total=row.queries_total,
        answers_with_sources=row.answers_with_sources,
        answers_without_sources=row.answers_without_sources,
        fallback_count=row.fallback_count,
        avg_retrieved_chunks=row.avg_retrieved_chunks,
        avg_retrieval_score=row.avg_retrieval_score,
        avg_latency_ms=row.avg_latency_ms,
    )


def to_retrieval_backend_metrics_payload(row: RetrievalBackendMetrics) -> RetrievalBackendMetricsPayload:
    return RetrievalBackendMetricsPayload(
        backend=row.backend,
        queries_total=row.queries_total,
        answers_with_sources=row.answers_with_sources,
        fallback_count=row.fallback_count,
        avg_retrieval_score=row.avg_retrieval_score,
        avg_latency_ms=row.avg_latency_ms,
    )


def to_retrieval_comparison_payload(row: RetrievalComparisonRow) -> RetrievalComparisonPayload:
    return RetrievalComparisonPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        current_backend=row.current_backend,
        baseline_backend=row.baseline_backend,
        current=to_retrieval_backend_metrics_payload(row.current),
        baseline=to_retrieval_backend_metrics_payload(row.baseline) if row.baseline else None,
        grounded_rate_delta=row.grounded_rate_delta,
        fallback_rate_delta=row.fallback_rate_delta,
        score_delta=row.score_delta,
        latency_delta_ms=row.latency_delta_ms,
    )


def to_rag_decision_record_payload(row: dict[str, object]) -> RagDecisionRecordPayload:
    return RagDecisionRecordPayload(
        recorded_at=str(row.get("recorded_at") or ""),
        agent_id=str(row.get("agent_id") or ""),
        company_id=str(row.get("company_id") or ""),
        decision=str(row.get("decision") or ""),
        current_backend=str(row.get("current_backend") or ""),
        baseline_backend=str(row.get("baseline_backend") or "").strip() or None,
        reason=str(row.get("reason") or ""),
        grounded_rate_delta=float(row["grounded_rate_delta"]) if row.get("grounded_rate_delta") is not None else None,
        fallback_rate_delta=float(row["fallback_rate_delta"]) if row.get("fallback_rate_delta") is not None else None,
        score_delta=float(row["score_delta"]) if row.get("score_delta") is not None else None,
        latency_delta_ms=float(row["latency_delta_ms"]) if row.get("latency_delta_ms") is not None else None,
    )


def to_evaluation_run_payload(row: dict[str, object]) -> EvaluationRunPayload:
    return EvaluationRunPayload(
        run_id=str(row.get("run_id") or ""),
        recorded_at=str(row.get("recorded_at") or ""),
        agent_id=str(row.get("agent_id") or ""),
        company_id=str(row.get("company_id") or ""),
        rag_backend=str(row.get("rag_backend") or ""),
        cases_total=int(row.get("cases_total") or 0),
        accuracy=float(row.get("accuracy") or 0.0),
        semantic_accuracy=float(row["semantic_accuracy"]) if row.get("semantic_accuracy") is not None else None,
        grounded_rate=float(row.get("grounded_rate") or 0.0),
        fallback_rate=float(row.get("fallback_rate") or 0.0),
        avg_case_score=float(row.get("avg_case_score") or 0.0),
        semantic_score_avg=float(row["semantic_score_avg"]) if row.get("semantic_score_avg") is not None else None,
        avg_latency_ms=float(row.get("avg_latency_ms") or 0.0),
        llm_judge_enabled=bool(row.get("llm_judge_enabled")),
        llm_judge_scored_cases=int(row.get("llm_judge_scored_cases") or 0),
    )


def to_evaluation_compare_payload(row: dict[str, object]) -> EvaluationComparePayload:
    current = row.get("current")
    baseline = row.get("baseline")
    return EvaluationComparePayload(
        agent_id=str(row.get("agent_id") or ""),
        company_id=str(row.get("company_id") or ""),
        current=to_evaluation_run_payload(current) if isinstance(current, dict) else None,
        baseline=to_evaluation_run_payload(baseline) if isinstance(baseline, dict) else None,
        accuracy_delta=float(row["accuracy_delta"]) if row.get("accuracy_delta") is not None else None,
        semantic_accuracy_delta=float(row["semantic_accuracy_delta"]) if row.get("semantic_accuracy_delta") is not None else None,
        grounded_rate_delta=float(row["grounded_rate_delta"]) if row.get("grounded_rate_delta") is not None else None,
        fallback_rate_delta=float(row["fallback_rate_delta"]) if row.get("fallback_rate_delta") is not None else None,
        avg_case_score_delta=float(row["avg_case_score_delta"]) if row.get("avg_case_score_delta") is not None else None,
        semantic_score_avg_delta=float(row["semantic_score_avg_delta"]) if row.get("semantic_score_avg_delta") is not None else None,
        avg_latency_ms_delta=float(row["avg_latency_ms_delta"]) if row.get("avg_latency_ms_delta") is not None else None,
    )


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def to_evaluation_job_payload(row: dict[str, Any]) -> EvaluationRunJobPayload:
    run_payload = row.get("run") if isinstance(row.get("run"), dict) else None
    return EvaluationRunJobPayload(
        job_id=str(row.get("job_id") or ""),
        agent_id=str(row.get("agent_id") or ""),
        company_id=str(row.get("company_id") or ""),
        status=str(row.get("status") or "queued"),
        sample_size=int(row["sample_size"]) if row.get("sample_size") is not None else None,
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        error=str(row.get("error") or "").strip() or None,
        run=to_evaluation_run_payload(run_payload) if run_payload else None,
    )


def evaluation_runs_to_csv(rows: list[dict[str, object]]) -> str:
    header = [
        "run_id", "recorded_at", "agent_id", "company_id", "rag_backend", "cases_total",
        "accuracy", "semantic_accuracy", "grounded_rate", "fallback_rate", "avg_case_score",
        "semantic_score_avg", "avg_latency_ms", "llm_judge_enabled", "llm_judge_scored_cases",
    ]

    def _escape(value: object) -> str:
        text = str(value if value is not None else "")
        text = text.replace('"', '""')
        return f'"{text}"'

    lines = [",".join(header)]
    for row in rows:
        values = [
            row.get("run_id"), row.get("recorded_at"), row.get("agent_id"), row.get("company_id"),
            row.get("rag_backend"), row.get("cases_total"), row.get("accuracy"), row.get("semantic_accuracy"),
            row.get("grounded_rate"), row.get("fallback_rate"), row.get("avg_case_score"), row.get("semantic_score_avg"),
            row.get("avg_latency_ms"), row.get("llm_judge_enabled"), row.get("llm_judge_scored_cases"),
        ]
        lines.append(",".join(_escape(value) for value in values))
    return "\n".join(lines)


def to_agent_feedback_summary_payload(row: AgentFeedbackSummary) -> AgentFeedbackSummaryPayload:
    return AgentFeedbackSummaryPayload(
        company_id=row.company_id,
        agent_id=row.agent_id,
        feedback_total=row.feedback_total,
        thumbs_up=row.thumbs_up,
        thumbs_down=row.thumbs_down,
        positive_rate=row.positive_rate,
        with_comment=row.with_comment,
        with_expected_answer=row.with_expected_answer,
    )


def cors_allowed_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://localhost:3001,http://localhost:4011,"
        "http://localhost:5500,http://127.0.0.1:3000,http://127.0.0.1:3001,"
        "http://127.0.0.1:4011,http://127.0.0.1:5500",
    )
    return [item.strip() for item in raw.split(",") if item.strip()]
