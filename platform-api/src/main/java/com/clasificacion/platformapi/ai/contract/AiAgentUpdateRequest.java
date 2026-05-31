package com.clasificacion.platformapi.ai.contract;

public record AiAgentUpdateRequest(
    String name,
    String objective,
    String tone,
    String description,
    String rag_backend,
    String generation_provider,
    Boolean use_openai_generation,
    String openai_model
) {
}
