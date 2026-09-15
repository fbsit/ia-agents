package com.clasificacion.platformapi.ai.contract;

import com.fasterxml.jackson.annotation.JsonInclude;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record AiAgentCreateRequest(
    String name,
    String objective,
    String tone,
    String description,
    String rag_backend,
    String generation_provider,
    Boolean use_openai_generation,
    String openai_model,
    String clubhx_tenant_id,
    String clubhx_shop_domain
) {
}
