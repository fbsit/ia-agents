package com.clasificacion.platformapi.ai.dto;

public record UpdateAgentRequest(
    String name,
    String objective,
    String tone,
    String description,
    String company_id,
    String org_id,
    String rag_backend,
    String generation_provider,
    Boolean use_openai_generation,
    String openai_model
) {
}
