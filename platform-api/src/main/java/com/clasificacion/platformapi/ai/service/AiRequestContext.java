package com.clasificacion.platformapi.ai.service;

public record AiRequestContext(
    String companyId,
    String orgId,
    String userId,
    String requestId
) {
}
