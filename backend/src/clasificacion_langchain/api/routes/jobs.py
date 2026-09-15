from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from clasificacion_langchain.api.schemas import EvaluationRunJobPayload, EvaluationRunRequestPayload
from clasificacion_langchain.api.support.presenters import now_iso, to_evaluation_job_payload

from ..dependencies import get_accessible_agent, get_principal, get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(tags=["jobs"])


@router.post("/agents/{agent_id}/evaluation/run-async", response_model=EvaluationRunJobPayload)
def run_evaluation_async(
    agent_id: str,
    payload: EvaluationRunRequestPayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> EvaluationRunJobPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    job_id = f"evaljob-{uuid4().hex[:12]}"
    row = {
        "job_id": job_id,
        "agent_id": agent.agent_id,
        "company_id": agent.company_id,
        "status": "queued",
        "sample_size": payload.sample_size,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "error": None,
        "run": None,
    }
    runtime.evaluation_job_store.create(row)
    runtime.evaluation_job_queue.enqueue(job_id)
    return to_evaluation_job_payload(row)


@router.get("/agents/{agent_id}/jobs/{job_id}", response_model=EvaluationRunJobPayload)
def get_evaluation_job(
    agent_id: str,
    job_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> EvaluationRunJobPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    row = runtime.evaluation_job_store.get(job_id)
    if row is None or str(row.get("agent_id") or "") != agent.agent_id:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return to_evaluation_job_payload(row)
