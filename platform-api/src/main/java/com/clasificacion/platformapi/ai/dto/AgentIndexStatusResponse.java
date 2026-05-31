package com.clasificacion.platformapi.ai.dto;

public record AgentIndexStatusResponse(
    String agent_id,
    boolean has_index,
    String indexed_at,
    int documents_total,
    int documents_indexed,
    int documents_failed,
    int documents_uploaded,
    String last_error
) {
}
