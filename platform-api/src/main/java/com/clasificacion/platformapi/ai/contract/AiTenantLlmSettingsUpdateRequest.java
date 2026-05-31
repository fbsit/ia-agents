package com.clasificacion.platformapi.ai.contract;

public record AiTenantLlmSettingsUpdateRequest(
    String company_id,
    String generation_provider,
    String openai_model,
    String anthropic_model,
    String openai_api_key,
    String anthropic_api_key,
    boolean clear_openai_api_key,
    boolean clear_anthropic_api_key
) {
}
