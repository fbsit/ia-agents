import { apiRequest } from "@/shared/api/client";
import type {
  Agent,
  AgentChatResult,
  AgentDocument,
  AgentDocumentContent,
  AgentWebAnalysis,
  AgentFeedbackSummary,
  AgentIndexResult,
  AgentIndexStatus,
  EvaluationCompare,
  EvaluationDataset,
  EvaluationRunJob,
  EvaluationRun,
  RagDecisionRecord,
  RetrievalComparison,
  RetrievalSummaryRow,
  AgentSetupStatus,
  AgentWhatsAppConfig,
  AgentWhatsAppValidation,
  AgentWidgetConfig,
  AgentUpdateInput
} from "@/shared/api/types";

export function listAgents(accessToken: string, companyId?: string) {
  const query = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
  return apiRequest<Agent[]>(`/agents${query}`, { method: "GET" }, accessToken);
}

export function createAgent(
  input: {
    name: string;
    objective: string;
    tone: string;
    description: string;
    company_id: string;
    rag_backend: "auto" | "tfidf" | "dense_openai" | "hybrid";
    generation_provider: "auto" | "openai" | "anthropic";
    use_openai_generation: boolean;
    openai_model: string;
  },
  accessToken: string
) {
  return apiRequest<Agent>(
    "/agents",
    {
      method: "POST",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export async function uploadAgentDocument(
  agentId: string,
  file: File,
  accessToken: string,
  operationalSection?: "facts" | "rules" | "contracts" | "permissions" | "feedback"
) {
  const formData = new FormData();
  formData.append("file", file);
  if (operationalSection) {
    formData.append("operational_section", operationalSection);
  }
  return apiRequest<AgentDocument>(
    `/agents/${encodeURIComponent(agentId)}/documents`,
    {
      method: "POST",
      body: formData
    },
    accessToken
  );
}

export function rebuildAgentIndex(agentId: string, accessToken: string) {
  return apiRequest<AgentIndexResult>(
    `/agents/${encodeURIComponent(agentId)}/index/rebuild`,
    {
      method: "POST"
    },
    accessToken
  );
}

export function getAgentDocuments(agentId: string, accessToken: string) {
  return apiRequest<AgentDocument[]>(
    `/agents/${encodeURIComponent(agentId)}/documents`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function getAgentDocumentContent(agentId: string, documentId: string, accessToken: string) {
  return apiRequest<AgentDocumentContent>(
    `/agents/${encodeURIComponent(agentId)}/documents/${encodeURIComponent(documentId)}/content`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function deleteAgentDocument(agentId: string, documentId: string, accessToken: string) {
  return apiRequest<{ status: string; document_id: string }>(
    `/agents/${encodeURIComponent(agentId)}/documents/${encodeURIComponent(documentId)}`,
    {
      method: "DELETE"
    },
    accessToken
  );
}

export function analyzeAgentWebUrl(
  agentId: string,
  input: {
    url: string;
    timeout_seconds?: number;
    max_chars?: number;
    max_points?: number;
  },
  accessToken: string
) {
  return apiRequest<AgentWebAnalysis>(
    `/agents/${encodeURIComponent(agentId)}/tools/analyze-url`,
    {
      method: "POST",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function getAgentIndexStatus(agentId: string, accessToken: string) {
  return apiRequest<AgentIndexStatus>(
    `/agents/${encodeURIComponent(agentId)}/index/status`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function updateAgent(agentId: string, input: AgentUpdateInput, accessToken: string) {
  return apiRequest<Agent>(
    `/agents/${encodeURIComponent(agentId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function deleteAgent(agentId: string, accessToken: string) {
  return apiRequest<{ status: string; agent_id: string }>(
    `/agents/${encodeURIComponent(agentId)}`,
    {
      method: "DELETE"
    },
    accessToken
  );
}

export function chatWithAgent(
  agentId: string,
  input: {
    message: string;
    top_k?: number;
    session_id?: string;
    use_openai_generation?: boolean;
    generation_provider?: "auto" | "openai" | "anthropic";
    generation_model?: string;
  },
  accessToken: string
) {
  return apiRequest<AgentChatResult>(
    `/agents/${encodeURIComponent(agentId)}/chat`,
    {
      method: "POST",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function getAgentWidgetConfig(agentId: string, accessToken: string) {
  return apiRequest<AgentWidgetConfig>(
    `/agents/${encodeURIComponent(agentId)}/widget-config`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function getAgentSetupStatus(agentId: string, accessToken: string) {
  return apiRequest<AgentSetupStatus>(
    `/agents/${encodeURIComponent(agentId)}/setup-status`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function getRetrievalSummary(
  accessToken: string,
  input?: {
    company_id?: string;
    days?: number;
  }
) {
  const params = new URLSearchParams();
  if (input?.company_id) {
    params.set("company_id", input.company_id);
  }
  if (typeof input?.days === "number") {
    params.set("days", String(input.days));
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiRequest<RetrievalSummaryRow[]>(
    `/reports/retrieval/summary${query}`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function getAgentRetrievalComparison(
  agentId: string,
  accessToken: string,
  input?: { days?: number }
) {
  const params = new URLSearchParams();
  if (typeof input?.days === "number") {
    params.set("days", String(input.days));
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiRequest<RetrievalComparison>(
    `/agents/${encodeURIComponent(agentId)}/retrieval/compare${query}`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function createAgentRagDecision(
  agentId: string,
  input: {
    decision: string;
    current_backend: string;
    baseline_backend?: string | null;
    reason: string;
    grounded_rate_delta?: number | null;
    fallback_rate_delta?: number | null;
    score_delta?: number | null;
    latency_delta_ms?: number | null;
  },
  accessToken: string
) {
  return apiRequest<RagDecisionRecord>(
    `/agents/${encodeURIComponent(agentId)}/retrieval/decision`,
    {
      method: "POST",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function getAgentRagDecisionHistory(agentId: string, accessToken: string) {
  return apiRequest<RagDecisionRecord[]>(
    `/agents/${encodeURIComponent(agentId)}/retrieval/decision-history`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function getAgentEvaluationDataset(agentId: string, accessToken: string) {
  return apiRequest<EvaluationDataset>(
    `/agents/${encodeURIComponent(agentId)}/evaluation/dataset`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function saveAgentEvaluationDataset(
  agentId: string,
  input: EvaluationDataset,
  accessToken: string
) {
  return apiRequest<EvaluationDataset>(
    `/agents/${encodeURIComponent(agentId)}/evaluation/dataset`,
    {
      method: "POST",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function runAgentEvaluation(
  agentId: string,
  input: {
    sample_size?: number;
  },
  accessToken: string
) {
  return apiRequest<EvaluationRun>(
    `/agents/${encodeURIComponent(agentId)}/evaluation/run`,
    {
      method: "POST",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function runAgentEvaluationAsync(
  agentId: string,
  input: {
    sample_size?: number;
  },
  accessToken: string
) {
  return apiRequest<EvaluationRunJob>(
    `/agents/${encodeURIComponent(agentId)}/evaluation/run-async`,
    {
      method: "POST",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function getAgentEvaluationJobStatus(
  agentId: string,
  jobId: string,
  accessToken: string
) {
  return apiRequest<EvaluationRunJob>(
    `/agents/${encodeURIComponent(agentId)}/evaluation/jobs/${encodeURIComponent(jobId)}`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function getAgentEvaluationRuns(
  agentId: string,
  accessToken: string,
  input?: { limit?: number }
) {
  const params = new URLSearchParams();
  if (typeof input?.limit === "number") {
    params.set("limit", String(input.limit));
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiRequest<EvaluationRun[]>(
    `/agents/${encodeURIComponent(agentId)}/evaluation/runs${query}`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function getAgentEvaluationCompareLatest(agentId: string, accessToken: string) {
  return apiRequest<EvaluationCompare>(
    `/agents/${encodeURIComponent(agentId)}/evaluation/compare-latest`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function exportAgentEvaluationRunsCsv(
  agentId: string,
  accessToken: string,
  input?: { limit?: number }
) {
  const params = new URLSearchParams();
  if (typeof input?.limit === "number") {
    params.set("limit", String(input.limit));
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiRequest<string>(
    `/agents/${encodeURIComponent(agentId)}/evaluation/runs.csv${query}`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function getAgentWhatsAppConfig(agentId: string, accessToken: string) {
  return apiRequest<AgentWhatsAppConfig>(
    `/agents/${encodeURIComponent(agentId)}/channels/whatsapp/config`,
    {
      method: "GET"
    },
    accessToken
  );
}

export function updateAgentWhatsAppConfig(
  agentId: string,
  input: {
    phone_number_id?: string;
    business_account_id?: string;
    verify_token?: string;
  },
  accessToken: string
) {
  return apiRequest<AgentWhatsAppConfig>(
    `/agents/${encodeURIComponent(agentId)}/channels/whatsapp/config`,
    {
      method: "PUT",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function validateAgentWhatsAppConfig(agentId: string, accessToken: string) {
  return apiRequest<AgentWhatsAppValidation>(
    `/agents/${encodeURIComponent(agentId)}/channels/whatsapp/validate`,
    {
      method: "POST"
    },
    accessToken
  );
}

export function createAgentFeedback(
  agentId: string,
  input: {
    rating: "up" | "down";
    question: string;
    answer: string;
    sources?: string[];
    comment?: string;
    expected_answer?: string;
    session_id?: string;
    source_channel?: string;
  },
  accessToken: string
) {
  return apiRequest<AgentFeedbackSummary>(
    `/agents/${encodeURIComponent(agentId)}/feedback`,
    {
      method: "POST",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function getAgentFeedbackSummary(
  agentId: string,
  accessToken: string,
  input?: { days?: number }
) {
  const params = new URLSearchParams();
  if (typeof input?.days === "number") {
    params.set("days", String(input.days));
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiRequest<AgentFeedbackSummary>(
    `/agents/${encodeURIComponent(agentId)}/feedback/summary${query}`,
    {
      method: "GET"
    },
    accessToken
  );
}
