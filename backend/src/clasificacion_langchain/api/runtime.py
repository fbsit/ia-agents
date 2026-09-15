from __future__ import annotations

from dataclasses import dataclass

from clasificacion_langchain.analytics import (
    build_agent_feedback_service_from_env,
    build_chat_audit_service_from_env,
    build_retrieval_audit_service_from_env,
)
from clasificacion_langchain.analytics.chat_audit import ChatAuditService
from clasificacion_langchain.analytics.feedback_audit import AgentFeedbackService
from clasificacion_langchain.analytics.retrieval_audit import RetrievalAuditService
from clasificacion_langchain.agents.service import AgentService
from clasificacion_langchain.auth.service import AuthService
from clasificacion_langchain.auth.token_service import TokenService
from clasificacion_langchain.evaluation.jobs import (
    EvaluationJobQueue,
    EvaluationJobStore,
    build_evaluation_job_queue_from_env,
    build_evaluation_job_store_from_env,
)
from clasificacion_langchain.api.support.runtime_builders import (
    build_agent_service,
    build_identity_stack,
    build_llm_settings_service,
    build_service,
    persistence_backend,
    sqlite_db_path,
)
from clasificacion_langchain.chat.service import ChatService
from clasificacion_langchain.settings.service import TenantLlmSettingsService
from clasificacion_langchain.tenancy.service import TenancyService


@dataclass(slots=True)
class RuntimeContainer:
    chat_service: ChatService
    auth_service: AuthService
    tenancy_service: TenancyService
    token_service: TokenService
    llm_settings_service: TenantLlmSettingsService
    agent_service: AgentService
    chat_audit_service: ChatAuditService
    retrieval_audit_service: RetrievalAuditService
    feedback_service: AgentFeedbackService
    evaluation_job_store: EvaluationJobStore
    evaluation_job_queue: EvaluationJobQueue


def build_runtime() -> RuntimeContainer:
    chat_service = build_service()
    auth_service, tenancy_service, token_service = build_identity_stack()
    llm_settings_service = build_llm_settings_service()
    agent_service = build_agent_service(llm_settings_service)
    chat_audit_service = build_chat_audit_service_from_env()
    retrieval_audit_service = build_retrieval_audit_service_from_env()
    feedback_service = build_agent_feedback_service_from_env()
    evaluation_job_store = build_evaluation_job_store_from_env(
        persistence_backend=persistence_backend(),
        sqlite_db_path=sqlite_db_path(),
    )
    evaluation_job_queue = build_evaluation_job_queue_from_env()
    return RuntimeContainer(
        chat_service=chat_service,
        auth_service=auth_service,
        tenancy_service=tenancy_service,
        token_service=token_service,
        llm_settings_service=llm_settings_service,
        agent_service=agent_service,
        chat_audit_service=chat_audit_service,
        retrieval_audit_service=retrieval_audit_service,
        feedback_service=feedback_service,
        evaluation_job_store=evaluation_job_store,
        evaluation_job_queue=evaluation_job_queue,
    )
