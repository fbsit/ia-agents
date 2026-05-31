package com.clasificacion.platformapi.ai.dto;

import java.util.List;

public record AgentIndexResponse(
    String agent_id,
    String backend,
    int total_documents,
    int total_chunks,
    List<String> companies,
    String index_path
) {
}
