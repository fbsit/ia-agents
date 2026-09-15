package com.clasificacion.platformapi.ai.dto;

import jakarta.validation.constraints.NotBlank;

public record CreateAgentRequest(
    @NotBlank String name,
    String objective,
    String tone,
    String description,
    String company_id,
    String org_id,
    String rag_backend,
    String generation_provider,
    Boolean use_openai_generation,
    String openai_model,
    String clubhx_tenant_id,
    String clubhx_shop_domain
) {
}
