import { apiRequest } from "@/shared/api/client";
import type { TenantLlmSettings } from "@/shared/api/types";

type UpdateTenantLlmSettingsInput = {
  company_id?: string;
  generation_provider?: "auto" | "openai" | "anthropic";
  openai_model?: string;
  anthropic_model?: string;
  openai_api_key?: string;
  anthropic_api_key?: string;
  clear_openai_api_key?: boolean;
  clear_anthropic_api_key?: boolean;
};

export function getTenantLlmSettings(accessToken: string, companyId?: string) {
  const query = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
  return apiRequest<TenantLlmSettings>(`/settings/llm${query}`, { method: "GET" }, accessToken);
}

export function updateTenantLlmSettings(accessToken: string, input: UpdateTenantLlmSettingsInput) {
  return apiRequest<TenantLlmSettings>(
    "/settings/llm",
    {
      method: "PUT",
      body: JSON.stringify(input)
    },
    accessToken
  );
}
