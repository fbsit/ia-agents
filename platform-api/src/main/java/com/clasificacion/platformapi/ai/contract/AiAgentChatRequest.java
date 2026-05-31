package com.clasificacion.platformapi.ai.contract;

import com.fasterxml.jackson.annotation.JsonInclude;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record AiAgentChatRequest(
    String message,
    Integer top_k,
    String session_id,
    Boolean use_openai_generation,
    String generation_provider,
    String generation_model
) {
}
