from __future__ import annotations

from fastapi import APIRouter, Depends

from clasificacion_langchain.api.schemas import AgentIndexPayload, AgentIndexStatusPayload
from clasificacion_langchain.api.support.agent_views import index_status_payload, rebuild_index_payload

from ..dependencies import get_accessible_agent, get_principal, get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(tags=["indexing"])


@router.post("/agents/{agent_id}/index/rebuild", response_model=AgentIndexPayload)
def rebuild_index(
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentIndexPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    return rebuild_index_payload(runtime, agent)


@router.get("/agents/{agent_id}/index/status", response_model=AgentIndexStatusPayload)
def get_index_status(
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentIndexStatusPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    return index_status_payload(runtime, agent)
