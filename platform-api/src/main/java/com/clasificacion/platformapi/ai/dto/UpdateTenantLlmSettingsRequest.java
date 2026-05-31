package com.clasificacion.platformapi.ai.dto;

public record UpdateTenantLlmSettingsRequest(
    String company_id,
    String org_id,
    String generation_provider,
    String openai_model,
    String anthropic_model,
    String openai_api_key,
    String anthropic_api_key,
    boolean clear_openai_api_key,
    boolean clear_anthropic_api_key
) {
}
