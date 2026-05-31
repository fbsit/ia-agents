package com.clasificacion.platformapi.ai.contract;

import java.util.Map;

public record AiRuntimeExecuteRequest(
    int version,
    Map<String, Object> input
) {
}
