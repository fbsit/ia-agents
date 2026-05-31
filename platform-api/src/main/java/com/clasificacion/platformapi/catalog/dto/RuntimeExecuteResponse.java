package com.clasificacion.platformapi.catalog.dto;

import java.util.Map;

public record RuntimeExecuteResponse(
    String execution_id,
    String type,
    String id,
    int version,
    String status,
    Map<String, Object> output
) {
}
