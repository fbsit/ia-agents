package com.clasificacion.platformapi.ai.contract;

public record AiAgentDocumentUploadRequest(
    String filename,
    String content_base64,
    String operational_section
) {
}
