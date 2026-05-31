package com.clasificacion.platformapi.ai.dto;

public record TenantLlmSettingsResponse(
    String company_id,
    String generation_provider,
    String openai_model,
    String anthropic_model,
    boolean has_openai_api_key,
    boolean has_anthropic_api_key,
    String openai_api_key_masked,
    String anthropic_api_key_masked,
    String openai_key_source,
    String anthropic_key_source,
    String updated_at
) {
}
