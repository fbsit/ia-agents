from __future__ import annotations

from fastapi import APIRouter, Depends

from clasificacion_langchain.api.schemas import AgentSetupStatusPayload
from clasificacion_langchain.api.support.agent_views import setup_status_payload

from ..dependencies import get_accessible_agent, get_principal, get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(tags=["setup"])


@router.get("/agents/{agent_id}/setup-status", response_model=AgentSetupStatusPayload)
def get_setup_status(
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentSetupStatusPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    return setup_status_payload(runtime, agent)
