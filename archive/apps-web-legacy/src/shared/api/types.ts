export type Membership = {
  org_id: string;
  role: string;
};

export type AuthTokens = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
};

export type LoginResponse = {
  user_id: string;
  email: string;
  memberships: Membership[];
  tokens: AuthTokens;
};

export type RegisterResponse = {
  user_id: string;
  email: string;
};

export type MeResponse = {
  user_id: string;
  email: string;
  memberships: Membership[];
};

export type CreateOrgResponse = {
  org_id: string;
  company_id: string;
  name: string;
};

export type Organization = {
  org_id: string;
  name: string;
  company_id: string;
  role: string;
};

export type Agent = {
  agent_id: string;
  org_id: string;
  company_id: string;
  name: string;
  objective: string;
  tone: string;
  description: string;
  rag_backend: string;
  generation_provider: "auto" | "openai" | "anthropic";
  use_openai_generation: boolean;
  openai_model: string;
  knowledge_dir: string;
  index_path: string;
  indexed_at: string | null;
  documents_count: number;
};

export type AgentDocument = {
  document_id: string;
  agent_id: string;
  filename: string;
  size_bytes: number;
  status: "uploaded" | "indexed" | "failed";
  indexed_at: string | null;
  error_message: string | null;
  created_at: string;
  operational_section: "facts" | "rules" | "contracts" | "permissions" | "feedback" | null;
  learning_summary: string | null;
  summary_updated_at: string | null;
};

export type AgentDocumentContent = {
  document_id: string;
  agent_id: string;
  filename: string;
  status: "uploaded" | "indexed" | "failed";
  created_at: string;
  content: string;
};

export type AgentWebAnalysis = {
  url: string;
  status_code: number;
  title: string;
  content_excerpt: string;
  key_points: string[];
  word_count: number;
};

export type AgentIndexResult = {
  agent_id: string;
  backend: string;
  total_documents: number;
  total_chunks: number;
  companies: string[];
  index_path: string;
};

export type AgentIndexStatus = {
  agent_id: string;
  has_index: boolean;
  indexed_at: string | null;
  documents_total: number;
  documents_indexed: number;
  documents_failed: number;
  documents_uploaded: number;
  last_error: string | null;
};

export type AgentChatResult = {
  agent_id: string;
  company_id: string;
  session_id: string;
  answer: string;
  sources: string[];
  intent_label?: string | null;
  route?: string | null;
  route_reason?: string | null;
  response_mode?: string | null;
  fallback_applied?: boolean;
  retrieval_min_score?: number | null;
};

export type AgentUpdateInput = {
  name?: string;
  objective?: string;
  tone?: string;
  description?: string;
  rag_backend?: "auto" | "tfidf" | "dense_openai" | "hybrid";
  generation_provider?: "auto" | "openai" | "anthropic";
  use_openai_generation?: boolean;
  openai_model?: string;
};

export type AgentWidgetConfig = {
  agent_id: string;
  widget_id: string;
  endpoint_url: string;
  widget_token: string;
  allowed_origins: string[];
  rate_limit_window_seconds: number;
  rate_limit_max_requests: number;
  snippet_html: string;
};

export type AgentWhatsAppConfig = {
  agent_id: string;
  company_id: string;
  webhook_url: string;
  phone_number_id: string | null;
  business_account_id: string | null;
  verify_token: string | null;
  updated_at: string | null;
};

export type AgentWhatsAppValidation = {
  agent_id: string;
  company_id: string;
  ready: boolean;
  has_phone_number_id: boolean;
  has_verify_token: boolean;
  server_has_access_token: boolean;
  company_map_ready: boolean;
  webhook_url: string;
  messages: string[];
};

export type AgentSetupStep = {
  id: string;
  label: string;
  description: string;
  ready: boolean;
  href: string;
};

export type AgentSetupStatus = {
  agent_id: string;
  company_id: string;
  agent_name: string;
  rag_backend: "auto" | "tfidf" | "dense_openai" | "hybrid";
  progress_percent: number;
  ready_to_publish: boolean;
  next_href: string | null;
  documents_total: number;
  documents_indexed: number;
  test_messages: number;
  steps: AgentSetupStep[];
};

export type RetrievalSummaryRow = {
  company_id: string;
  agent_id: string;
  queries_total: number;
  answers_with_sources: number;
  answers_without_sources: number;
  fallback_count: number;
  avg_retrieved_chunks: number;
  avg_retrieval_score: number;
  avg_latency_ms: number;
};

export type RetrievalBackendMetrics = {
  backend: string;
  queries_total: number;
  answers_with_sources: number;
  fallback_count: number;
  avg_retrieval_score: number;
  avg_latency_ms: number;
};

export type RetrievalComparison = {
  company_id: string;
  agent_id: string;
  current_backend: string;
  baseline_backend: string | null;
  current: RetrievalBackendMetrics;
  baseline: RetrievalBackendMetrics | null;
  grounded_rate_delta: number | null;
  fallback_rate_delta: number | null;
  score_delta: number | null;
  latency_delta_ms: number | null;
};

export type RagDecisionRecord = {
  recorded_at: string;
  agent_id: string;
  company_id: string;
  decision: string;
  current_backend: string;
  baseline_backend: string | null;
  reason: string;
  grounded_rate_delta: number | null;
  fallback_rate_delta: number | null;
  score_delta: number | null;
  latency_delta_ms: number | null;
};

export type EvaluationCase = {
  question: string;
  expected_answer: string;
};

export type EvaluationDataset = {
  cases: EvaluationCase[];
};

export type EvaluationRun = {
  run_id: string;
  recorded_at: string;
  agent_id: string;
  company_id: string;
  rag_backend: string;
  cases_total: number;
  accuracy: number;
  semantic_accuracy: number | null;
  grounded_rate: number;
  fallback_rate: number;
  avg_case_score: number;
  semantic_score_avg: number | null;
  avg_latency_ms: number;
  llm_judge_enabled: boolean;
  llm_judge_scored_cases: number;
};

export type EvaluationCompare = {
  agent_id: string;
  company_id: string;
  current: EvaluationRun | null;
  baseline: EvaluationRun | null;
  accuracy_delta: number | null;
  semantic_accuracy_delta: number | null;
  grounded_rate_delta: number | null;
  fallback_rate_delta: number | null;
  avg_case_score_delta: number | null;
  semantic_score_avg_delta: number | null;
  avg_latency_ms_delta: number | null;
};

export type EvaluationRunJob = {
  job_id: string;
  agent_id: string;
  company_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  sample_size: number | null;
  created_at: string;
  updated_at: string;
  error: string | null;
  run: EvaluationRun | null;
};

export type AgentFeedbackSummary = {
  company_id: string;
  agent_id: string;
  feedback_total: number;
  thumbs_up: number;
  thumbs_down: number;
  positive_rate: number;
  with_comment: number;
  with_expected_answer: number;
};

export type TenantLlmSettings = {
  company_id: string;
  generation_provider: "auto" | "openai" | "anthropic";
  openai_model: string;
  anthropic_model: string;
  has_openai_api_key: boolean;
  has_anthropic_api_key: boolean;
  openai_api_key_masked: string | null;
  anthropic_api_key_masked: string | null;
  openai_key_source: "tenant" | "env" | "none";
  anthropic_key_source: "tenant" | "env" | "none";
  updated_at: string;
};
