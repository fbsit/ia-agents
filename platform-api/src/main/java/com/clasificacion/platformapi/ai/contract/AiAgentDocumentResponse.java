package com.clasificacion.platformapi.ai.contract;

public record AiAgentDocumentResponse(
    String document_id,
    String agent_id,
    String filename,
    int size_bytes,
    String status,
    String indexed_at,
    String error_message,
    String created_at,
    String operational_section,
    String learning_summary,
    String summary_updated_at
) {
}
