package com.clasificacion.platformapi.ai.contract;

public record AiErrorResponse(
    String code,
    String detail,
    String request_id
) {
}
