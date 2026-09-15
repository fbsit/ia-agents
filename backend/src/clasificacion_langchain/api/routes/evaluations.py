from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from clasificacion_langchain.api.schemas import (
    EvaluationComparePayload,
    EvaluationDatasetPayload,
    EvaluationRunPayload,
)
from clasificacion_langchain.api.support.presenters import (
    evaluation_runs_to_csv,
    to_evaluation_compare_payload,
    to_evaluation_run_payload,
)

from ..dependencies import get_accessible_agent, get_principal, get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(tags=["evaluations"])


@router.get("/agents/{agent_id}/evaluation/dataset", response_model=EvaluationDatasetPayload)
def get_evaluation_dataset(
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> EvaluationDatasetPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    return EvaluationDatasetPayload(cases=runtime.agent_service.get_evaluation_dataset(agent))


@router.post("/agents/{agent_id}/evaluation/dataset", response_model=EvaluationDatasetPayload)
def save_evaluation_dataset(
    agent_id: str,
    payload: EvaluationDatasetPayload,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> EvaluationDatasetPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    saved = runtime.agent_service.save_evaluation_dataset(agent, payload.cases)
    return EvaluationDatasetPayload(cases=saved)


@router.post("/agents/{agent_id}/evaluation/run", response_model=EvaluationRunPayload)
def run_evaluation(
    agent_id: str,
    sample_size: int | None = None,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> EvaluationRunPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    run = runtime.agent_service.run_evaluation(agent, sample_size=sample_size)
    return to_evaluation_run_payload(run)


@router.get("/agents/{agent_id}/evaluation/runs", response_model=list[EvaluationRunPayload])
def list_evaluation_runs(
    agent_id: str,
    limit: int = 20,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> list[EvaluationRunPayload]:
    agent = get_accessible_agent(runtime, principal, agent_id)
    rows = runtime.agent_service.list_evaluation_runs(agent, limit=max(1, limit))
    return [to_evaluation_run_payload(row) for row in rows]


@router.get("/agents/{agent_id}/evaluation/runs.csv", response_class=PlainTextResponse)
def list_evaluation_runs_csv(
    agent_id: str,
    limit: int = 20,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> str:
    agent = get_accessible_agent(runtime, principal, agent_id)
    rows = runtime.agent_service.list_evaluation_runs(agent, limit=max(1, limit))
    return evaluation_runs_to_csv(rows)


@router.get("/agents/{agent_id}/evaluation/compare-latest", response_model=EvaluationComparePayload)
def compare_latest_evaluation_runs(
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> EvaluationComparePayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    return to_evaluation_compare_payload(runtime.agent_service.compare_latest_evaluation_runs(agent))
