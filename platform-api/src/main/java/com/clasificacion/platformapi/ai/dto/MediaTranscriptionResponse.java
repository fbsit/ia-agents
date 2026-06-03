package com.clasificacion.platformapi.ai.dto;

public record MediaTranscriptionResponse(
    String text,
    String language,
    Double confidence,
    Integer duration_ms,
    String provider
) {
}
