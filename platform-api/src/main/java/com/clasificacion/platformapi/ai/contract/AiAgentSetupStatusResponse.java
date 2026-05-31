package com.clasificacion.platformapi.ai.contract;

import java.util.List;

public record AiAgentSetupStatusResponse(
    String agent_id,
    String company_id,
    String agent_name,
    String rag_backend,
    int progress_percent,
    boolean ready_to_publish,
    String next_href,
    int documents_total,
    int documents_indexed,
    int test_messages,
    List<AiAgentSetupStepResponse> steps
) {
}
