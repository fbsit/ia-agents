from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from clasificacion_langchain.analytics.feedback_audit import AgentFeedbackRecord
from clasificacion_langchain.api.schemas import AgentFeedbackCreatePayload, AgentFeedbackSummaryPayload
from clasificacion_langchain.api.support.presenters import to_agent_feedback_summary_payload

from ..dependencies import get_accessible_agent, get_principal, get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(tags=["feedback"])


@router.post("/agents/{agent_id}/feedback", response_model=AgentFeedbackSummaryPayload)
def record_feedback(
    agent_id: str,
    payload: AgentFeedbackCreatePayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentFeedbackSummaryPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    rating = payload.rating.strip().lower()
    if rating not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="rating invalido")
    runtime.feedback_service.record(
        AgentFeedbackRecord(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            rating=rating,
            question=payload.question,
            answer=payload.answer,
            sources=payload.sources,
            comment=payload.comment,
            expected_answer=payload.expected_answer,
            session_id=payload.session_id,
            source_channel=payload.source_channel,
        )
    )
    summary = runtime.feedback_service.summary(agent.company_id, agent.agent_id)
    return to_agent_feedback_summary_payload(summary)


@router.get("/agents/{agent_id}/feedback/summary", response_model=AgentFeedbackSummaryPayload)
def feedback_summary(
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentFeedbackSummaryPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    summary = runtime.feedback_service.summary(agent.company_id, agent.agent_id)
    return to_agent_feedback_summary_payload(summary)
