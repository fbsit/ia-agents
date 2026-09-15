from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from clasificacion_langchain.agents.service import AgentValidationError
from clasificacion_langchain.api.schemas import RagDecisionCreatePayload, RagDecisionRecordPayload, RetrievalComparisonPayload
from clasificacion_langchain.api.support.presenters import (
    to_rag_decision_record_payload,
    to_retrieval_comparison_payload,
)

from ..dependencies import get_accessible_agent, get_principal, get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(tags=["retrieval"])


@router.post("/agents/{agent_id}/retrieval/decision", response_model=RagDecisionRecordPayload)
def save_rag_decision(
    agent_id: str,
    payload: RagDecisionCreatePayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> RagDecisionRecordPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    try:
        row = runtime.agent_service.save_rag_decision(
            agent=agent,
            decision=payload.decision,
            current_backend=payload.current_backend,
            baseline_backend=payload.baseline_backend,
            reason=payload.reason,
            grounded_rate_delta=payload.grounded_rate_delta,
            fallback_rate_delta=payload.fallback_rate_delta,
            score_delta=payload.score_delta,
            latency_delta_ms=payload.latency_delta_ms,
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_rag_decision_record_payload(row)


@router.get("/agents/{agent_id}/retrieval/decision-history", response_model=list[RagDecisionRecordPayload])
def list_rag_decision_history(
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> list[RagDecisionRecordPayload]:
    agent = get_accessible_agent(runtime, principal, agent_id)
    rows = runtime.agent_service.list_rag_decision_history(agent)
    return [to_rag_decision_record_payload(row) for row in rows]


@router.get("/agents/{agent_id}/retrieval/compare", response_model=RetrievalComparisonPayload)
def compare_retrieval(
    agent_id: str,
    since_days: int = 30,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> RetrievalComparisonPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    row = runtime.retrieval_audit_service.compare_agent_backends(
        company_id=agent.company_id,
        agent_id=agent.agent_id,
        current_backend=agent.rag_backend,
        since_days=since_days,
    )
    return to_retrieval_comparison_payload(row)
