package com.clasificacion.platformapi.ai.contract;

import java.util.Map;

public record AiRuntimeExecuteResponse(
    String execution_id,
    String type,
    String id,
    int version,
    String status,
    Map<String, Object> output
) {
}
