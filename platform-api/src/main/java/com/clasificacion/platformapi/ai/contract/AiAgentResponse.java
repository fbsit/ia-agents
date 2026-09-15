package com.clasificacion.platformapi.ai.contract;

public record AiAgentResponse(
    String agent_id,
    String org_id,
    String company_id,
    String name,
    String objective,
    String tone,
    String description,
    String rag_backend,
    String generation_provider,
    boolean use_openai_generation,
    String openai_model,
    String knowledge_dir,
    String index_path,
    String indexed_at,
    int documents_count,
    String clubhx_tenant_id,
    String clubhx_shop_domain,
    String clubhx_storefront_url
) {
}
