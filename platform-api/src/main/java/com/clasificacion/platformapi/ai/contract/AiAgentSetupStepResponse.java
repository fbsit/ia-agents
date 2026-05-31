package com.clasificacion.platformapi.ai.contract;

public record AiAgentSetupStepResponse(
    String id,
    String label,
    String description,
    boolean ready,
    String href
) {
}
