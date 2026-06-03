package com.clasificacion.platformapi.ai.dto;

import jakarta.validation.constraints.NotBlank;

public record AgentChatRequest(
    @NotBlank String message,
    Integer top_k,
    String session_id,
    String channel,
    Boolean use_openai_generation,
    String generation_provider,
    String generation_model,
    String company_id,
    String org_id
) {
}
