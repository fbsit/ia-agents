from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequestPayload(BaseModel):
    company_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    message: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)
    generation_provider: str | None = Field(default=None)
    generation_model: str | None = Field(default=None)
    use_openai_generation: bool | None = Field(default=None)


class AgentCreatePayload(BaseModel):
    name: str = Field(min_length=2)
    objective: str = Field(default="Responder consultas de la empresa", min_length=8)
    tone: str = Field(default="profesional", min_length=3)
    description: str = ""
    company_id: str | None = Field(default=None, min_length=1)
    rag_backend: str = Field(default="auto")
    generation_provider: str = Field(default="auto")
    use_openai_generation: bool = False
    openai_model: str | None = Field(default=None, min_length=3)
    clubhx_tenant_id: str | None = None
    clubhx_shop_domain: str | None = None
    clubhx_storefront_url: str | None = None


class AgentUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=2)
    objective: str | None = Field(default=None, min_length=8)
    tone: str | None = Field(default=None, min_length=3)
    description: str | None = None
    rag_backend: str | None = None
    generation_provider: str | None = None
    use_openai_generation: bool | None = None
    openai_model: str | None = Field(default=None, min_length=3)
    clubhx_tenant_id: str | None = None
    clubhx_shop_domain: str | None = None
    clubhx_storefront_url: str | None = None


class AgentPayload(BaseModel):
    agent_id: str
    org_id: str
    company_id: str
    name: str
    objective: str
    tone: str
    description: str
    rag_backend: str
    generation_provider: str
    use_openai_generation: bool
    openai_model: str
    knowledge_dir: str
    index_path: str
    indexed_at: str | None
    documents_count: int
    clubhx_tenant_id: str | None = None
    clubhx_shop_domain: str | None = None
    clubhx_storefront_url: str | None = None
    commerce_enabled: bool = False


class AgentDocumentPayload(BaseModel):
    document_id: str
    agent_id: str
    filename: str
    size_bytes: int
    status: str
    indexed_at: str | None
    error_message: str | None
    created_at: str
    operational_section: str | None = None
    learning_summary: str | None = None
    summary_updated_at: str | None = None


class AgentDocumentContentPayload(BaseModel):
    document_id: str
    agent_id: str
    filename: str
    status: str
    created_at: str
    content: str


class AgentWebAnalysisRequestPayload(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    timeout_seconds: int = Field(default=15, ge=3, le=60)
    max_chars: int = Field(default=18000, ge=500, le=120000)
    max_points: int = Field(default=5, ge=1, le=12)


class AgentWebAnalysisPayload(BaseModel):
    url: str
    status_code: int
    title: str
    content_excerpt: str
    key_points: list[str]
    word_count: int


class AgentIndexStatusPayload(BaseModel):
    agent_id: str
    has_index: bool
    indexed_at: str | None
    documents_total: int
    documents_indexed: int
    documents_failed: int
    documents_uploaded: int
    last_error: str | None


class AgentIndexPayload(BaseModel):
    agent_id: str
    backend: str
    total_documents: int
    total_chunks: int
    companies: list[str]
    index_path: str


class AgentChatRequestPayload(BaseModel):
    message: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)
    session_id: str | None = Field(default=None, min_length=1)
    channel: str | None = Field(default=None, min_length=1)
    use_openai_generation: bool | None = None
    generation_provider: str | None = None
    generation_model: str | None = Field(default=None, min_length=3)


class InternalAgentDocumentUploadPayload(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=4)
    operational_section: str | None = None


class TenantLlmSettingsUpdatePayload(BaseModel):
    company_id: str | None = Field(default=None, min_length=1)
    generation_provider: str | None = None
    openai_model: str | None = Field(default=None, min_length=3)
    anthropic_model: str | None = Field(default=None, min_length=3)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    clear_openai_api_key: bool = False
    clear_anthropic_api_key: bool = False


class TenantLlmSettingsPayload(BaseModel):
    company_id: str
    generation_provider: str
    openai_model: str
    anthropic_model: str
    has_openai_api_key: bool
    has_anthropic_api_key: bool
    openai_api_key_masked: str | None
    anthropic_api_key_masked: str | None
    openai_key_source: str
    anthropic_key_source: str
    updated_at: str


class AgentChatResponsePayload(BaseModel):
    agent_id: str
    company_id: str
    session_id: str
    answer: str
    sources: list[str]
    intent_label: str | None = None
    route: str | None = None
    route_reason: str | None = None
    response_mode: str | None = None
    fallback_applied: bool = False
    retrieval_min_score: float | None = None
    redirect_to: str | None = None
    workflow_action: dict[str, Any] | None = None
    cart_action: dict[str, Any] | None = None
    cart_actions: list[dict[str, Any]] | None = None
    products: list[dict[str, Any]] | None = None


class InternalRuntimeExecuteRequestPayload(BaseModel):
    version: int = Field(ge=1)
    input: dict[str, Any] | None = None


class InternalRuntimeExecuteResponsePayload(BaseModel):
    execution_id: str
    type: str
    id: str
    version: int
    status: str
    output: dict[str, Any]


class AgentWidgetConfigPayload(BaseModel):
    agent_id: str
    widget_id: str
    endpoint_url: str
    widget_token: str
    allowed_origins: list[str]
    rate_limit_window_seconds: int
    rate_limit_max_requests: int
    snippet_html: str


class AgentWhatsAppConfigPayload(BaseModel):
    agent_id: str
    company_id: str
    webhook_url: str
    phone_number_id: str | None = None
    business_account_id: str | None = None
    verify_token: str | None = None
    updated_at: str | None = None


class AgentWhatsAppConfigUpdatePayload(BaseModel):
    phone_number_id: str | None = None
    business_account_id: str | None = None
    verify_token: str | None = None


class AgentWhatsAppValidationPayload(BaseModel):
    agent_id: str
    company_id: str
    ready: bool
    has_phone_number_id: bool
    has_verify_token: bool
    server_has_access_token: bool
    company_map_ready: bool
    webhook_url: str
    messages: list[str]


class AgentSetupStepPayload(BaseModel):
    id: str
    label: str
    description: str
    ready: bool
    href: str


class AgentSetupStatusPayload(BaseModel):
    agent_id: str
    company_id: str
    agent_name: str
    rag_backend: str
    progress_percent: int
    ready_to_publish: bool
    next_href: str | None
    documents_total: int
    documents_indexed: int
    test_messages: int
    steps: list[AgentSetupStepPayload]


class PublicWidgetChatRequestPayload(BaseModel):
    widget_id: str = Field(min_length=1)
    widget_token: str = Field(min_length=8)
    message: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    visitor_id: str | None = Field(default=None, min_length=1)
    external_user_id: str | None = Field(default=None, min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)


class PublicWidgetChatResponsePayload(BaseModel):
    widget_id: str
    session_id: str
    answer: str
    sources: list[str]
    route: str | None = None
    intent_label: str | None = None
    response_mode: str | None = None
    redirect_to: str | None = None
    workflow_action: dict[str, Any] | None = None
    cart_action: dict[str, Any] | None = None
    cart_actions: list[dict[str, Any]] | None = None
    products: list[dict[str, Any]] | None = None


class MediaTranscriptionPayload(BaseModel):
    text: str
    language: str | None = None
    confidence: float | None = None
    duration_ms: int | None = None
    provider: str | None = None


class MediaTranscriptionRequestPayload(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=4)
    mime_type: str | None = None
    language_hint: str | None = None
    channel: str | None = None
    source: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    phone_number_id: str | None = None


class ChatAuditSummaryRowPayload(BaseModel):
    company_id: str
    agent_id: str
    assistant_messages: int
    cached_responses: int
    generic_repeat_responses: int
    closed_conversations: int


class ChatAuditCostRowPayload(BaseModel):
    company_id: str
    agent_id: str
    assistant_messages: int
    llm_messages: int
    avoided_llm_calls: int
    estimated_spent_usd: float
    estimated_saved_usd: float


class RetrievalAuditSummaryRowPayload(BaseModel):
    company_id: str
    agent_id: str
    queries_total: int
    answers_with_sources: int
    answers_without_sources: int
    fallback_count: int
    avg_retrieved_chunks: float
    avg_retrieval_score: float
    avg_latency_ms: float


class RetrievalBackendMetricsPayload(BaseModel):
    backend: str
    queries_total: int
    answers_with_sources: int
    fallback_count: int
    avg_retrieval_score: float
    avg_latency_ms: float


class RetrievalComparisonPayload(BaseModel):
    company_id: str
    agent_id: str
    current_backend: str
    baseline_backend: str | None
    current: RetrievalBackendMetricsPayload
    baseline: RetrievalBackendMetricsPayload | None
    grounded_rate_delta: float | None
    fallback_rate_delta: float | None
    score_delta: float | None
    latency_delta_ms: float | None


class RagDecisionCreatePayload(BaseModel):
    decision: str = Field(min_length=2, max_length=80)
    current_backend: str = Field(min_length=2, max_length=32)
    baseline_backend: str | None = Field(default=None, min_length=2, max_length=32)
    reason: str = Field(min_length=6, max_length=800)
    grounded_rate_delta: float | None = None
    fallback_rate_delta: float | None = None
    score_delta: float | None = None
    latency_delta_ms: float | None = None


class RagDecisionRecordPayload(BaseModel):
    recorded_at: str
    agent_id: str
    company_id: str
    decision: str
    current_backend: str
    baseline_backend: str | None
    reason: str
    grounded_rate_delta: float | None
    fallback_rate_delta: float | None
    score_delta: float | None
    latency_delta_ms: float | None


class EvaluationCasePayload(BaseModel):
    question: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)


class EvaluationDatasetPayload(BaseModel):
    cases: list[EvaluationCasePayload] = Field(default_factory=list)


class EvaluationRunPayload(BaseModel):
    run_id: str
    recorded_at: str
    agent_id: str
    company_id: str
    rag_backend: str
    cases_total: int
    accuracy: float
    semantic_accuracy: float | None
    grounded_rate: float
    fallback_rate: float
    avg_case_score: float
    semantic_score_avg: float | None
    avg_latency_ms: float
    llm_judge_enabled: bool
    llm_judge_scored_cases: int


class EvaluationRunRequestPayload(BaseModel):
    sample_size: int | None = Field(default=None, ge=1, le=500)


class EvaluationRunJobPayload(BaseModel):
    job_id: str
    agent_id: str
    company_id: str
    status: str
    sample_size: int | None
    created_at: str
    updated_at: str
    error: str | None = None
    run: EvaluationRunPayload | None = None


class EvaluationComparePayload(BaseModel):
    agent_id: str
    company_id: str
    current: EvaluationRunPayload | None
    baseline: EvaluationRunPayload | None
    accuracy_delta: float | None
    semantic_accuracy_delta: float | None
    grounded_rate_delta: float | None
    fallback_rate_delta: float | None
    avg_case_score_delta: float | None
    semantic_score_avg_delta: float | None
    avg_latency_ms_delta: float | None


class AgentFeedbackCreatePayload(BaseModel):
    rating: str = Field(min_length=2, max_length=8)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    sources: list[str] = Field(default_factory=list)
    comment: str | None = None
    expected_answer: str | None = None
    session_id: str | None = Field(default=None, min_length=1)
    source_channel: str | None = Field(default=None, min_length=1)


class AgentFeedbackSummaryPayload(BaseModel):
    company_id: str
    agent_id: str
    feedback_total: int
    thumbs_up: int
    thumbs_down: int
    positive_rate: float
    with_comment: int
    with_expected_answer: int


class ChatResponsePayload(BaseModel):
    trace_id: str
    company_id: str
    session_id: str
    answer: str
    route: str
    route_reason: str
    intent_label: str
    intent_confidence: float
    sources: list[str]
    escalation_required: bool
    delivery_status: str | None = None
    delivery_message_id: str | None = None
    delivery_error: str | None = None


class ConversationSummaryPayload(BaseModel):
    session_id: str
    channel: str
    status: str
    message_count: int
    started_at: str
    updated_at: str
    visitor_id: str | None = None
    external_user_id: str | None = None
    authenticated_user_id: str | None = None
    last_message_preview: str


class ConversationMessagePayload(BaseModel):
    role: str
    message_text: str
    created_at: str
    intent_label: str | None = None


class ConversationReplyRequestPayload(BaseModel):
    message: str = Field(min_length=1)


class ConversationReplyResponsePayload(BaseModel):
    delivered: bool
    channel: str


class ConversationStatusResponsePayload(BaseModel):
    session_id: str
    status: str
