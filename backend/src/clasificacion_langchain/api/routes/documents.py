from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from clasificacion_langchain.agents.service import AgentDocumentNotFoundError, AgentValidationError
from clasificacion_langchain.api.schemas import AgentDocumentContentPayload, AgentDocumentPayload
from clasificacion_langchain.api.support.presenters import document_content_payload, document_payload

from ..dependencies import get_accessible_agent, get_principal, get_runtime
from ..runtime import RuntimeContainer


router = APIRouter(tags=["documents"])


@router.get("/agents/{agent_id}/documents", response_model=list[AgentDocumentPayload])
def list_documents(
    agent_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> list[AgentDocumentPayload]:
    agent = get_accessible_agent(runtime, principal, agent_id)
    return [document_payload(item) for item in runtime.agent_service.list_documents(agent.agent_id)]


@router.get("/agents/{agent_id}/documents/{document_id}/content", response_model=AgentDocumentContentPayload)
def get_document_content(
    agent_id: str,
    document_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentDocumentContentPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    try:
        document, content = runtime.agent_service.read_document_text(agent, document_id)
    except AgentDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return document_content_payload(document, content)


@router.post("/agents/{agent_id}/documents", response_model=AgentDocumentPayload)
async def upload_document(
    agent_id: str,
    file: UploadFile = File(...),
    operational_section: str | None = None,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentDocumentPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    content = await file.read()
    try:
        document = runtime.agent_service.save_document(
            agent=agent,
            filename=file.filename or "documento.bin",
            content=content,
            operational_section=operational_section,
        )
    except AgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return document_payload(document)


@router.delete("/agents/{agent_id}/documents/{document_id}", response_model=AgentDocumentPayload)
def delete_document(
    agent_id: str,
    document_id: str,
    principal=Depends(get_principal),
    runtime: RuntimeContainer = Depends(get_runtime),
) -> AgentDocumentPayload:
    agent = get_accessible_agent(runtime, principal, agent_id)
    try:
        document = runtime.agent_service.delete_document(agent, document_id)
    except AgentDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return document_payload(document)
