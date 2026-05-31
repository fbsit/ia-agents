package com.clasificacion.platformapi.ai.dto;

public record AgentSetupStepResponse(
    String id,
    String label,
    String description,
    boolean ready,
    String href
) {
}
