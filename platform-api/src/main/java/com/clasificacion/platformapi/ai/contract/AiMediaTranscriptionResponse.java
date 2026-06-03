package com.clasificacion.platformapi.ai.contract;

public record AiMediaTranscriptionResponse(
    String text,
    String language,
    Double confidence,
    Integer duration_ms,
    String provider
) {
}
