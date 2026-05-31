package com.clasificacion.platformapi.ai.contract;

import java.util.List;

public record AiAgentIndexResponse(
    String agent_id,
    String backend,
    int total_documents,
    int total_chunks,
    List<String> companies,
    String index_path
) {
}
