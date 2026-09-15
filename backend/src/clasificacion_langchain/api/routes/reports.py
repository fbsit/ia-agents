from __future__ import annotations

from fastapi import APIRouter, Depends

from clasificacion_langchain.api.schemas import ChatAuditCostRowPayload, ChatAuditSummaryRowPayload, RetrievalAuditSummaryRowPayload
from clasificacion_langchain.api.support.presenters import (
    to_audit_cost_payload,
    to_audit_summary_payload,
    to_retrieval_summary_payload,
)

from ..dependencies import (
    get_principal,
    get_runtime,
    resolve_report_companies,
)
from ..runtime import RuntimeContainer


router = APIRouter(tags=["reports"])


@router.get("/reports/chat/summary", response_model=list[ChatAuditSummaryRowPayload])
def chat_summary(
    company_id: str | None = None,
    since_days: int = 30,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> list[ChatAuditSummaryRowPayload]:
    companies = set(resolve_report_companies(runtime, principal, company_id))
    rows = runtime.chat_audit_service.summary(since_days=since_days)
    return [to_audit_summary_payload(row) for row in rows if row.company_id in companies]


@router.get("/reports/chat/cost-estimate", response_model=list[ChatAuditCostRowPayload])
def chat_cost_estimate(
    company_id: str | None = None,
    since_days: int = 30,
    avg_llm_cost_usd: float = 0.01,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> list[ChatAuditCostRowPayload]:
    companies = set(resolve_report_companies(runtime, principal, company_id))
    rows = runtime.chat_audit_service.cost_summary(avg_llm_cost_usd=avg_llm_cost_usd, since_days=since_days)
    return [to_audit_cost_payload(row) for row in rows if row.company_id in companies]


@router.get("/reports/retrieval/summary", response_model=list[RetrievalAuditSummaryRowPayload])
def retrieval_summary(
    company_id: str | None = None,
    since_days: int = 30,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> list[RetrievalAuditSummaryRowPayload]:
    companies = set(resolve_report_companies(runtime, principal, company_id))
    rows = runtime.retrieval_audit_service.summary(since_days=since_days)
    return [to_retrieval_summary_payload(row) for row in rows if row.company_id in companies]
