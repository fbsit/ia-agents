from __future__ import annotations

import logging
import os
import threading
import time

from fastapi import HTTPException

from clasificacion_langchain.analytics.chat_audit import ChatAuditRecord
from clasificacion_langchain.analytics.retrieval_audit import RetrievalAuditRecord
from clasificacion_langchain.auth.schemas import AuthPrincipal
from clasificacion_langchain.tenancy.service import TenantContextError, TenantForbiddenError


logger = logging.getLogger(__name__)

WORKFLOW_REMINDER_SCAN_SECONDS = 15

evaluation_worker_started = False
workflow_reminder_worker_started = False

_chat_audit_service = None
_retrieval_audit_service = None
_agent_service = None
_evaluation_job_store = None
_evaluation_job_queue = None
_tenancy_service = None


def setup_services(
    *,
    chat_audit_service=None,
    retrieval_audit_service=None,
    agent_service=None,
    evaluation_job_store=None,
    evaluation_job_queue=None,
    tenancy_service=None,
) -> None:
    global _chat_audit_service, _retrieval_audit_service
    global _agent_service, _evaluation_job_store, _evaluation_job_queue
    global _tenancy_service
    if chat_audit_service is not None:
        _chat_audit_service = chat_audit_service
    if retrieval_audit_service is not None:
        _retrieval_audit_service = retrieval_audit_service
    if agent_service is not None:
        _agent_service = agent_service
    if evaluation_job_store is not None:
        _evaluation_job_store = evaluation_job_store
    if evaluation_job_queue is not None:
        _evaluation_job_queue = evaluation_job_queue
    if tenancy_service is not None:
        _tenancy_service = tenancy_service


def run_evaluation_job_worker(*, job_id: str) -> None:
    if _agent_service is None:
        row = _evaluation_job_store.get(job_id)
        if row is None:
            return
        _evaluation_job_store.update(job_id, status="failed", error="Agent service no disponible")
        return
    row = _evaluation_job_store.get(job_id)
    if row is None:
        return
    agent_id = str(row.get("agent_id") or "").strip()
    if not agent_id:
        _evaluation_job_store.update(job_id, status="failed", error="agent_id faltante en job")
        return
    agent = _agent_service.repository.get_agent(agent_id)
    if agent is None:
        _evaluation_job_store.update(job_id, status="failed", error="Agente del job no encontrado")
        return
    sample_size = int(row["sample_size"]) if row.get("sample_size") is not None else None
    _evaluation_job_store.update(job_id, status="running", error=None)
    try:
        run = _agent_service.run_evaluation(agent=agent, sample_size=sample_size)
        _evaluation_job_store.update(job_id, status="succeeded", error=None, run=run)
    except Exception as exc:  # noqa: BLE001
        _evaluation_job_store.update(job_id, status="failed", error=str(exc))


def evaluation_worker_loop() -> None:
    logger.info("evaluation_worker_started")
    while True:
        try:
            job_id = _evaluation_job_queue.dequeue(timeout_seconds=2)
            if not job_id:
                continue
            run_evaluation_job_worker(job_id=job_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("evaluation_worker_loop_error detail=%s", exc)


def start_evaluation_worker_once() -> None:
    global evaluation_worker_started
    if evaluation_worker_started:
        return
    worker = threading.Thread(target=evaluation_worker_loop, daemon=True, name="evaluation-worker")
    worker.start()
    evaluation_worker_started = True


def workflow_reminder_scan_seconds() -> int:
    raw = os.getenv("WORKFLOW_REMINDER_SCAN_SECONDS", str(WORKFLOW_REMINDER_SCAN_SECONDS)).strip()
    try:
        return max(5, int(raw or str(WORKFLOW_REMINDER_SCAN_SECONDS)))
    except ValueError:
        return WORKFLOW_REMINDER_SCAN_SECONDS


def workflow_reminder_worker_enabled() -> bool:
    return os.getenv("WORKFLOW_REMINDER_WORKER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def workflow_reminder_worker_loop(*, process_fn) -> None:
    logger.info("workflow_reminder_worker_started")
    while True:
        try:
            process_fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_reminder_worker_loop_error detail=%s", exc)
        time.sleep(workflow_reminder_scan_seconds())


def start_workflow_reminder_worker_once(*, process_fn) -> None:
    global workflow_reminder_worker_started
    if workflow_reminder_worker_started:
        return
    worker = threading.Thread(
        target=lambda: workflow_reminder_worker_loop(process_fn=process_fn),
        daemon=True,
        name="workflow-reminder-worker",
    )
    worker.start()
    workflow_reminder_worker_started = True


def embedded_worker_enabled() -> bool:
    return os.getenv("EVAL_EMBEDDED_WORKER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def record_chat_audit(record: ChatAuditRecord) -> None:
    if _chat_audit_service is None:
        return
    try:
        _chat_audit_service.record(record)
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat_audit_record_failed detail=%s", exc)


def record_retrieval_audit(record: RetrievalAuditRecord) -> None:
    if _retrieval_audit_service is None:
        return
    try:
        _retrieval_audit_service.record(record)
    except Exception as exc:  # noqa: BLE001
        logger.warning("retrieval_audit_record_failed detail=%s", exc)


def resolve_report_companies(principal: AuthPrincipal, company_id: str | None) -> list[str]:
    if _tenancy_service is None:
        raise HTTPException(status_code=503, detail="Tenancy no disponible")
    memberships = _tenancy_service.membership_repository.list_memberships(principal.user_id)
    allowed_org_ids = {membership.org_id for membership in memberships}
    if company_id:
        try:
            resolved = _tenancy_service.resolve_company_id(principal=principal, requested_company_id=company_id)
        except TenantContextError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except TenantForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return [resolved]
    discovered: set[str] = set()
    for org_id in allowed_org_ids:
        org = _tenancy_service.organization_repository.get_organization(org_id)
        if org is not None:
            discovered.add(org.company_id)
    return sorted(discovered)
